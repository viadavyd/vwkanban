import pytest

from vwkanban.auth.passwords import hash_password, verify_password
from vwkanban.auth.validation import check_password, normalize_username


async def test_hash_is_argon2id_and_verifies():
    h = await hash_password("correct horse")
    assert h.startswith("$argon2id$")
    assert await verify_password(h, "correct horse") == (True, None)
    assert (await verify_password(h, "wrong horse"))[0] is False


async def test_verify_unknown_user_fails():
    assert await verify_password(None, "whatever") == (False, None)


def test_username_rules():
    assert normalize_username(" Alice.B ") == "alice.b"
    for bad in ["ab", "a" * 33, "has space", "ümlaut", "x/y"]:
        with pytest.raises(ValueError):
            normalize_username(bad)


def test_password_rules():
    assert check_password("12345678") == "12345678"
    with pytest.raises(ValueError):
        check_password("1234567")
    with pytest.raises(ValueError):
        check_password("x" * 1025)
