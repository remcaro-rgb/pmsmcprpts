"""FNS passwords stored in pms.fns_hotels, encrypted with FNS_SECRET_KEY (the same key in the agent,
which saves them, and here, which uses them). agent/pms_agent/fns_hotels.py has the same code."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "fernet:"


def _fernet(key: str) -> Fernet:
    if not key:
        raise ValueError("FNS_SECRET_KEY is not set: add it to .env to store FNS passwords per hotel.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt(value: str, key: str) -> str:
    return PREFIX + _fernet(key).encrypt(value.encode()).decode()


def decrypt(stored: str, key: str) -> str:
    if not stored.startswith(PREFIX):
        raise ValueError("the stored FNS password is not in a known format; enter it again in the Admin page.")
    try:
        return _fernet(key).decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise ValueError("the stored FNS password can't be read with this FNS_SECRET_KEY; enter it again in "
                         "the Admin page.") from None
