# privilege_selector.py
import hashlib

def get_privilege(username):
    """
    Check if the given username is privileged.
    A username is considered privileged if it ends with '@ubbcluj.ro'.

    :param username: The username to check.
    :return: 1 if privileged, 0 otherwise.
    """
    username = username.lower()
    if username.endswith("@ubbcluj.ro"):
        return 1
    elif username == "admin" or username == "mlhubdev_admin":
        return 1
    else:
        return 0


def get_safe_username(username):
    # Define the prefixes based on domain
    if username.endswith("@ubbcluj.ro"):
        prefix = "md5_t"
    elif username.endswith("@stud.ubbcluj.ro"):
        prefix = "md5_s"
    else:
        prefix = "md5_u"
    
    # Compute the MD5 hash of the username
    hash_digest = hashlib.md5(username.encode('utf-8')).hexdigest()

    # Truncate the hash so the total length is at most 32 characters
    max_hash_length = 32 - len(prefix)
    safe_username = f"{prefix}{hash_digest[:max_hash_length]}"
    
    return safe_username