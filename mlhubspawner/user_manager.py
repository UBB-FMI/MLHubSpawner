import asyncio
import base64
import hashlib
import logging
import secrets
from typing import Optional

from .account_manager import get_privilege

try:
    from ldap3 import Connection, Server, NONE, SUBTREE
except ImportError:
    Connection = None
    Server = None
    NONE = None
    SUBTREE = None


DEFAULT_LOGIN_SHELL = "/bin/bash"
DEFAULT_CREATE_RETRY_ATTEMPTS = 3


class UserManager:
    def __init__(
        self,
        logger: Optional[logging.Logger],
        *,
        ldap_uri: str,
        ldap_base_dn: str,
        ldap_users_dn: str,
        ldap_bind_cn: str,
        ldap_bind_password: str,
        ldap_home_prefix: str,
        ldap_students_gid: int,
        ldap_teachers_gid: int,
        create_retry_attempts: int = DEFAULT_CREATE_RETRY_ATTEMPTS,
    ):
        self.log = logger or logging.getLogger(__name__)
        self.ldap_uri = ldap_uri
        self.ldap_base_dn = ldap_base_dn
        self.ldap_users_dn = ldap_users_dn
        self.ldap_bind_cn = ldap_bind_cn
        self.ldap_bind_password = ldap_bind_password
        self.ldap_home_prefix = ldap_home_prefix
        self.ldap_students_gid = int(ldap_students_gid)
        self.ldap_teachers_gid = int(ldap_teachers_gid)
        self.create_retry_attempts = max(1, int(create_retry_attempts))

    async def ensure_user_exists(self, jupyter_username: str, safe_username: str) -> bool:
        return await asyncio.to_thread(
            self._ensure_user_exists_sync,
            jupyter_username,
            safe_username,
        )

    def _ensure_user_exists_sync(self, jupyter_username: str, safe_username: str) -> bool:
        last_error = None

        for attempt in range(1, self.create_retry_attempts + 1):
            connection = self._connect()
            try:
                if self._find_user_entry(connection, safe_username) is not None:
                    self.log.info("LDAP user %s already exists.", safe_username)
                    return False

                user_dn = f"uid={safe_username},{self.ldap_users_dn}"
                uid_number = self._allocate_uid_number(connection)
                attributes = self._build_user_attributes(
                    jupyter_username=jupyter_username,
                    safe_username=safe_username,
                    uid_number=uid_number,
                )

                if connection.add(user_dn, attributes=attributes):
                    self.log.info(
                        "Created LDAP user %s with uidNumber=%s and gidNumber=%s.",
                        safe_username,
                        attributes["uidNumber"],
                        attributes["gidNumber"],
                    )
                    return True

                result = getattr(connection, "result", {}) or {}
                last_error = self._build_add_error(safe_username, result)
                if self._is_retryable_add_failure(result):
                    self.log.warning(
                        "Retrying LDAP user creation for %s after add failure on attempt %s/%s: %s",
                        safe_username,
                        attempt,
                        self.create_retry_attempts,
                        result,
                    )
                    continue

                raise last_error
            finally:
                self._unbind_quietly(connection)

        verification_connection = self._connect()
        try:
            if self._find_user_entry(verification_connection, safe_username) is not None:
                self.log.info("LDAP user %s became visible after a retry race.", safe_username)
                return False
        finally:
            self._unbind_quietly(verification_connection)

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Unable to create LDAP user {safe_username}.")

    def _connect(self):
        if Server is None or Connection is None:
            raise RuntimeError("ldap3 is required to manage LDAP users.")
        bind_dn = self._build_bind_dn()
        if not bind_dn:
            raise RuntimeError("LDAP bind CN is not configured.")
        if not self.ldap_bind_password:
            raise RuntimeError("LDAP bind password is not configured.")

        server = Server(self.ldap_uri, get_info=NONE)
        connection = Connection(
            server,
            user=bind_dn,
            password=self.ldap_bind_password,
            auto_bind=False,
            raise_exceptions=False,
        )
        if not connection.bind():
            result = getattr(connection, "result", {}) or {}
            self._unbind_quietly(connection)
            raise RuntimeError(f"LDAP bind failed for {bind_dn}: {result}")
        return connection

    def _build_bind_dn(self) -> str:
        bind_cn = str(self.ldap_bind_cn or "").strip()
        if not bind_cn:
            return ""
        if "=" in bind_cn and "," in bind_cn:
            return bind_cn
        return f"cn={bind_cn},{self.ldap_base_dn}"

    def _find_user_entry(self, connection, safe_username: str):
        search_ok = connection.search(
            search_base=self.ldap_users_dn,
            search_filter=f"(uid={safe_username})",
            search_scope=SUBTREE,
            attributes=["uid", "uidNumber", "gidNumber", "mail"],
        )
        result = getattr(connection, "result", {}) or {}
        if not self._search_succeeded(search_ok, result):
            result = getattr(connection, "result", {}) or {}
            raise RuntimeError(f"LDAP search failed for {safe_username}: {result}")

        entries = getattr(connection, "entries", None) or []
        return entries[0] if entries else None

    def _allocate_uid_number(self, connection) -> int:
        search_ok = connection.search(
            search_base=self.ldap_users_dn,
            search_filter="(uidNumber=*)",
            search_scope=SUBTREE,
            attributes=["uidNumber"],
        )
        result = getattr(connection, "result", {}) or {}
        if not self._search_succeeded(search_ok, result):
            result = getattr(connection, "result", {}) or {}
            raise RuntimeError(f"LDAP uidNumber search failed: {result}")

        existing_uid_numbers = []
        for entry in getattr(connection, "entries", None) or []:
            uid_number = self._entry_attribute_value(entry, "uidNumber")
            if uid_number is None:
                continue
            try:
                existing_uid_numbers.append(int(uid_number))
            except (TypeError, ValueError):
                continue

        if existing_uid_numbers:
            return max(existing_uid_numbers) + 1
        return max(self.ldap_students_gid, self.ldap_teachers_gid) + 1

    def _build_user_attributes(self, *, jupyter_username: str, safe_username: str, uid_number: int):
        gid_number = self._gid_for_username(jupyter_username)
        return {
            "objectClass": ["inetOrgPerson", "posixAccount", "shadowAccount"],
            "uid": safe_username,
            "cn": safe_username,
            "sn": safe_username,
            "mail": jupyter_username,
            "uidNumber": str(uid_number),
            "gidNumber": str(gid_number),
            "homeDirectory": self._build_home_directory(safe_username),
            "loginShell": DEFAULT_LOGIN_SHELL,
            "userPassword": self._generate_ssha_password_hash(),
        }

    def _gid_for_username(self, jupyter_username: str) -> int:
        if get_privilege(jupyter_username) >= 1:
            return self.ldap_teachers_gid
        return self.ldap_students_gid

    def _build_home_directory(self, safe_username: str) -> str:
        normalized_prefix = self.ldap_home_prefix.rstrip("/")
        if not normalized_prefix:
            return f"/{safe_username}"
        return f"{normalized_prefix}/{safe_username}"

    def _generate_ssha_password_hash(self) -> str:
        password = secrets.token_bytes(24)
        salt = secrets.token_bytes(4)
        digest = hashlib.sha1(password + salt).digest()
        return "{SSHA}" + base64.b64encode(digest + salt).decode("ascii")

    def _entry_attribute_value(self, entry, attribute_name: str):
        if entry is None:
            return None

        if isinstance(entry, dict):
            value = entry.get(attribute_name)
            if isinstance(value, (list, tuple)):
                return value[0] if value else None
            return value

        attribute = None
        if hasattr(entry, attribute_name):
            attribute = getattr(entry, attribute_name)
        else:
            try:
                attribute = entry[attribute_name]
            except Exception:
                attribute = None

        if attribute is None:
            return None

        value = getattr(attribute, "value", attribute)
        if isinstance(value, (list, tuple)):
            return value[0] if value else None
        return value

    def _is_retryable_add_failure(self, result) -> bool:
        description = str(result.get("description", "")).strip().lower()
        message = str(result.get("message", "")).strip().lower()
        retryable_descriptions = {
            "entryalreadyexists",
            "constraintviolation",
            "typeorvalueexists",
        }
        return (
            description in retryable_descriptions
            or "already exists" in message
            or "duplicate" in message
            or "uidnumber" in message
        )

    def _search_succeeded(self, search_ok, result) -> bool:
        result_code = result.get("result")
        description = str(result.get("description", "")).strip().lower()
        if result_code is not None:
            try:
                return int(result_code) == 0
            except (TypeError, ValueError):
                pass
        if description:
            return description == "success"
        return bool(search_ok)

    def _build_add_error(self, safe_username: str, result):
        description = str(result.get("description", "")).strip().lower()
        if description == "insufficientaccessrights":
            return RuntimeError(
                f"LDAP bind account {self._build_bind_dn()} cannot create users under {self.ldap_users_dn}: {result}"
            )
        return RuntimeError(f"LDAP add failed for {safe_username}: {result}")

    def _unbind_quietly(self, connection):
        if connection is None:
            return
        try:
            connection.unbind()
        except Exception:
            pass
