import pytest

from src.helpers.security import hash_password, verify_password


def test_round_trip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password!", h)


def test_hash_is_salted_and_not_plaintext():
    a, b = hash_password("same-password-1"), hash_password("same-password-1")
    assert a != b
    assert "same-password-1" not in a
    assert a.startswith("pbkdf2_sha256$")


def test_short_password_rejected():
    with pytest.raises(ValueError, match="8"):
        hash_password("short")


def test_unicode_password_supported():
    h = hash_password("كلمة-سر-قوية-123")
    assert verify_password("كلمة-سر-قوية-123", h)
    assert not verify_password("كلمة-سر-قوية-124", h)


@pytest.mark.parametrize("bad", ["", "garbage", "a$b$c$d", "md5$1$x$y", "pbkdf2_sha256$notint$AAAA$AAAA"])
def test_malformed_hash_never_raises(bad):
    assert verify_password("whatever-123", bad) is False
