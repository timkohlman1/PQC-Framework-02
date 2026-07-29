import json, secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def normalize_identity(first: str, last: str, dob_iso: str, postcode: str) -> bytes:
    # Same canonical form you used in the seeder
    s = "|".join([first.strip().lower(),
                  last.strip().lower(),
                  postcode.strip().upper(),
                  dob_iso.strip()])
    return s.encode()

def aes_gcm_encrypt_json(dek: bytes, obj: dict):
    """Returns (nonce12, ciphertext, tag16)."""
    aes = AESGCM(dek)
    nonce = secrets.token_bytes(12)  # 96-bit
    pt = json.dumps(obj, separators=(",", ":")).encode()
    ct = aes.encrypt(nonce, pt, None)  # ciphertext||tag
    return nonce, ct[:-16], ct[-16:]

def aes_gcm_decrypt_json(dek: bytes, nonce: bytes, ciphertext: bytes, tag: bytes) -> dict:
    aes = AESGCM(dek)
    pt = aes.decrypt(nonce, ciphertext + tag, None)
    return json.loads(pt.decode("utf-8"))
