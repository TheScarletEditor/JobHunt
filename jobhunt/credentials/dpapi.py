"""Windows DPAPI wrapper for at-rest encryption of secrets."""
import win32crypt


def encrypt(plaintext: str) -> bytes:
    if not plaintext:
        return b""
    blob = win32crypt.CryptProtectData(
        plaintext.encode("utf-8"),
        "JobHunt",
        None, None, None, 0,
    )
    return blob


def decrypt(ciphertext: bytes) -> str:
    if not ciphertext:
        return ""
    _description, plaintext = win32crypt.CryptUnprotectData(
        ciphertext, None, None, None, 0,
    )
    return plaintext.decode("utf-8")
