import re

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
PASSWORD_MIN = 8
PASSWORD_MAX = 1024


def normalize_username(raw: str) -> str:
    """Lowercases and validates a username; raises ValueError if it is invalid."""
    name = raw.strip().lower()
    if not USERNAME_RE.fullmatch(name):
        raise ValueError("username must be 3-32 characters: a-z 0-9 _ . -")
    return name


def check_password(password: str) -> str:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ValueError(f"password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters")
    return password
