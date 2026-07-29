#!/usr/bin/env python3
from __future__ import annotations
import os, base64, hashlib
from typing import Any, Dict, Tuple, Optional

from .vault import (
    login_approle,
    hmac_sha256,
    encrypt_rsa_oaep,
    decrypt_rsa_oaep,
    DEFAULT_VAULT_ADDR,
)
from .crypto import (
    normalize_identity,
    aes_gcm_encrypt_json,
    aes_gcm_decrypt_json,
)

def _vault_addr(vault_addr: str | None) -> str:
    return (vault_addr or os.getenv("VAULT_ADDR") or DEFAULT_VAULT_ADDR).rstrip("/")

def voter_hash_b32(voter_guid: str) -> str:
    tag = hashlib.sha256(voter_guid.encode()).digest()[:20]  # 160-bit
    return "VH-" + base64.b32encode(tag).decode().rstrip("=")

def build_voter_blob(
    *,
    first_name: str,
    last_name: str,
    dob_iso: str,         # "YYYY-MM-DD"
    postcode: str,
    pii: Dict[str, Any],  # will be JSON-encoded and encrypted
    token: str | None = None,
    vault_addr: str | None = None,
    ik_name: str = "ik-hmac",
    kek_name: str = "kek-rsa",
    enc_version: int = 1,
    reason: str | None = None,
    voter_guid: str | None = None,
    request_id: str | None = None,
    audit_extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Returns a dict you can persist directly into your Voter columns:
      {
        "lookup_hash": bytes(32),
        "ik_version": int,
        "kek_version": int,
        "enc_version": int,
        "dek_wrapped": "vault:vN:<BASE64>",
        "nonce": bytes(12),
        "auth_tag": bytes(16),
        "ciphertext": bytes(...),
      }
    """
    vaddr = _vault_addr(vault_addr)
    tok = token or login_approle(vault_addr=vaddr)
    audit = {
        "X-Request-ID": request_id,
        "X-Purpose": reason,
        "X-Voter-Hash": voter_hash_b32(voter_guid) if voter_guid else None,
    }
    if audit_extra:
        audit.update({k: v for k, v in audit_extra.items() if v})

    # 1) blind index (HMAC over normalized identity)
    norm = normalize_identity(first_name, last_name, dob_iso, postcode)
    lookup_hash, ik_version = hmac_sha256(tok, norm, key_name=ik_name, vault_addr=vaddr, audit=audit)

    # 2) encrypt PII with fresh DEK (AES-256-GCM)
    import secrets
    dek = secrets.token_bytes(32)
    nonce, ciphertext, auth_tag = aes_gcm_encrypt_json(dek, pii)

    # 3) wrap DEK with Vault RSA-3072 KEK (OAEP/SHA-256)
    dek_wrapped, kek_version = encrypt_rsa_oaep(tok, dek, key_name=kek_name, vault_addr=vaddr, audit=audit)

    return {
        "lookup_hash": lookup_hash,
        "ik_version": ik_version,
        "kek_version": kek_version,
        "enc_version": enc_version,
        "dek_wrapped": dek_wrapped,
        "nonce": nonce,
        "auth_tag": auth_tag,
        "ciphertext": ciphertext,
    }

def compute_lookup_hash(
    *,
    first_name: str,
    last_name: str,
    dob_iso: str,
    postcode: str,
    token: str | None = None,
    vault_addr: str | None = None,
    ik_name: str = "ik-hmac",
    reason: str | None = None,
    voter_guid: str | None = None,
    request_id: str | None = None,
    audit_extra: Optional[Dict[str, str]] = None,
) -> Tuple[bytes, int]:
    """Convenience for read-path: returns (lookup_hash_bytes, ik_version)."""
    vaddr = _vault_addr(vault_addr)
    tok = token or login_approle(vault_addr=vaddr)
    audit = {
        "X-Request-ID": request_id,
        "X-Purpose": reason,
        "X-Voter-Hash": voter_hash_b32(voter_guid) if voter_guid else None,
    }
    if audit_extra:
        audit.update({k: v for k, v in audit_extra.items() if v})

    norm = normalize_identity(first_name, last_name, dob_iso, postcode)
    return hmac_sha256(tok, norm, key_name=ik_name, vault_addr=vaddr, audit=audit)

def _get_attr_or_key(obj: Any, name: str) -> Any:
    """Supports SQLAlchemy row object or dict-like."""
    if hasattr(obj, name):
        return getattr(obj, name)
    try:
        return obj[name]
    except Exception as _:
        raise AttributeError(f"Object has no attribute or key '{name}'")

def decrypt_voter_blob(
    row_or_mapping: Any,
    *,
    token: str | None = None,
    vault_addr: str | None = None,
    kek_name: str = "kek-rsa",
    reason: str | None = None,
    voter_guid: str | None = None,
    request_id: str | None = None,
    audit_extra: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Given a DB row with fields: dek_wrapped (str), nonce, auth_tag, ciphertext (bytes),
    unwrap the DEK via Vault and return the decrypted PII dict.
    """
    vaddr = _vault_addr(vault_addr)
    tok = token or login_approle(vault_addr=vaddr)
    audit = {
        "X-Request-ID": request_id,
        "X-Purpose": reason,
        "X-Voter-Hash": voter_hash_b32(voter_guid) if voter_guid else None,
    }
    if audit_extra:
        audit.update({k: v for k, v in audit_extra.items() if v})

    dek_wrapped = _get_attr_or_key(row_or_mapping, "dek_wrapped")
    nonce       = _get_attr_or_key(row_or_mapping, "nonce")
    auth_tag    = _get_attr_or_key(row_or_mapping, "auth_tag")
    ciphertext  = _get_attr_or_key(row_or_mapping, "ciphertext")

    dek = decrypt_rsa_oaep(tok, dek_wrapped, key_name=kek_name, vault_addr=vaddr, audit=audit)
    return aes_gcm_decrypt_json(dek, nonce, ciphertext, auth_tag)
