from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


DEFAULT_SSH_PORT = 22


def normalize_endpoint(raw_endpoint: str) -> Tuple[str, int]:
    if raw_endpoint.count(":") == 1:
        hostname, port = raw_endpoint.rsplit(":", 1)
        if port.isdigit():
            return hostname, int(port)
    return raw_endpoint, DEFAULT_SSH_PORT


def build_endpoint(hostname: str, ssh_port: int) -> str:
    return f"{hostname}:{ssh_port}"


@dataclass(eq=False)
class MachineType:
    type_id: str
    codename: str
    shared_access_enabled: bool
    privileged_access_required: bool
    display_data: Dict[str, object]
    instances: Tuple["MachineInstance", ...] = ()

    def total_instances(self) -> int:
        return len(self.instances)

    def to_display_dict(self, include_instances: bool = False) -> Dict[str, object]:
        data = dict(self.display_data)
        data["type_id"] = self.type_id
        data["codename"] = self.codename
        data["total_instances"] = self.total_instances()
        data["shared_access_enabled"] = self.shared_access_enabled
        data["privileged_access_required"] = self.privileged_access_required
        if include_instances:
            data["instances"] = [machine_instance.to_display_dict() for machine_instance in self.instances]
        return data


@dataclass(eq=False)
class MachineInstance:
    # Runtime code passes these shared objects around directly, so identity-based
    # equality is intentional here.
    instance_id: str
    machine_type: MachineType
    hostname: str
    ssh_port: int
    assigned_users: Dict[str, bool] = field(default_factory=dict)

    @property
    def endpoint(self) -> str:
        return build_endpoint(self.hostname, self.ssh_port)

    @property
    def display_hostname(self) -> str:
        return self.hostname

    @property
    def allocation_count(self) -> int:
        return len(self.assigned_users)

    @property
    def has_allocations(self) -> bool:
        return bool(self.assigned_users)

    @property
    def has_exclusive_allocation(self) -> bool:
        return any(not shared_access_enabled for shared_access_enabled in self.assigned_users.values())

    def assign_user(self, unique_identifier: str, shared_access_enabled: bool):
        self.assigned_users[unique_identifier] = shared_access_enabled

    def release_user(self, unique_identifier: str):
        self.assigned_users.pop(unique_identifier, None)

    def to_display_dict(self) -> Dict[str, object]:
        return {
            "instance_id": self.instance_id,
            "hostname": self.display_hostname,
            "endpoint": self.endpoint,
            "assigned_user_count": self.allocation_count,
            "has_allocations": self.has_allocations,
            "has_exclusive_allocation": self.has_exclusive_allocation,
        }


class MachineRegistry:
    def __init__(self, machine_types: Sequence[MachineType], machine_instances: Sequence[MachineInstance], config_signature: str):
        self.machine_types = tuple(machine_types)
        self.machine_instances = tuple(machine_instances)
        self.config_signature = config_signature

        self._types_by_id = {machine_type.type_id: machine_type for machine_type in self.machine_types}
        self._instances_by_id = {machine_instance.instance_id: machine_instance for machine_instance in self.machine_instances}
        self._instances_by_endpoint = {machine_instance.endpoint: machine_instance for machine_instance in self.machine_instances}

    @classmethod
    def from_config(cls, remote_hosts_config_objects: Sequence[object]) -> "MachineRegistry":
        machine_types: List[MachineType] = []
        machine_instances: List[MachineInstance] = []
        type_ids = set()
        instance_ids = set()
        endpoints = set()

        for remote_host in remote_hosts_config_objects:
            type_id = str(getattr(remote_host, "codename"))
            if type_id in type_ids:
                raise ValueError(f"Duplicate machine type codename detected: {type_id}")
            type_ids.add(type_id)

            machine_type = MachineType(
                type_id=type_id,
                codename=getattr(remote_host, "codename"),
                shared_access_enabled=getattr(remote_host, "shared_access_enabled"),
                privileged_access_required=getattr(remote_host, "privileged_access_required"),
                display_data=_get_display_data(remote_host),
            )

            instances_for_type = []
            for raw_endpoint in getattr(remote_host, "hostnames", []):
                hostname, ssh_port = normalize_endpoint(raw_endpoint)
                endpoint = build_endpoint(hostname, ssh_port)
                instance_id = f"{type_id}|{endpoint}"

                if instance_id in instance_ids:
                    raise ValueError(f"Duplicate machine instance id detected: {instance_id}")
                if endpoint in endpoints:
                    raise ValueError(f"Duplicate machine endpoint detected: {endpoint}")

                instance_ids.add(instance_id)
                endpoints.add(endpoint)

                machine_instance = MachineInstance(
                    instance_id=instance_id,
                    machine_type=machine_type,
                    hostname=hostname,
                    ssh_port=ssh_port,
                )
                instances_for_type.append(machine_instance)
                machine_instances.append(machine_instance)

            machine_type.instances = tuple(instances_for_type)
            machine_types.append(machine_type)

        return cls(
            machine_types=machine_types,
            machine_instances=machine_instances,
            config_signature=cls.compute_config_signature(remote_hosts_config_objects),
        )

    @staticmethod
    def compute_config_signature(remote_hosts_config_objects: Sequence[object]) -> str:
        signature_payload = []
        for remote_host in remote_hosts_config_objects:
            normalized_endpoints = [build_endpoint(*normalize_endpoint(raw_endpoint)) for raw_endpoint in getattr(remote_host, "hostnames", [])]
            signature_payload.append(
                {
                    "codename": getattr(remote_host, "codename", None),
                    "shared_access_enabled": getattr(remote_host, "shared_access_enabled", None),
                    "privileged_access_required": getattr(remote_host, "privileged_access_required", None),
                    "display_data": _get_display_data(remote_host),
                    "endpoints": normalized_endpoints,
                }
            )
        return json.dumps(signature_payload, sort_keys=True)

    def get_type(self, type_id: str) -> Optional[MachineType]:
        return self._types_by_id.get(type_id)

    def get_instance(self, instance_id: str) -> Optional[MachineInstance]:
        return self._instances_by_id.get(instance_id)

    def get_instance_by_endpoint(self, endpoint: str) -> Optional[MachineInstance]:
        hostname, ssh_port = normalize_endpoint(endpoint)
        return self._instances_by_endpoint.get(build_endpoint(hostname, ssh_port))

    def resolve_instance(self, identifier: Optional[str]) -> Optional[MachineInstance]:
        if not identifier:
            return None
        return self.get_instance(identifier) or self.get_instance_by_endpoint(identifier)


def _get_display_data(remote_host: object) -> Dict[str, object]:
    if hasattr(remote_host, "toDictionary"):
        return dict(remote_host.toDictionary())

    return {
        key: value
        for key, value in vars(remote_host).items()
        if not key.startswith("_")
    }
