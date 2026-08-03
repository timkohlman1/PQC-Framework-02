from pathlib import Path
import re

from scripts.framework.tls_algorithms import TLS_GROUPS, resolve_tls_algorithm_set


def _scalar(text: str, key: str) -> str:
    matches = re.findall(rf"^\s*{re.escape(key)}:\s*([^#\n]+?)\s*$", text, re.MULTILINE)
    assert matches, f"missing YAML scalar: {key}"
    return matches[-1].strip().strip('"\'')


def test_server_and_mutual_profiles_share_group_capabilities():
    for group, capabilities in TLS_GROUPS.items():
        mode_prefix = "pqc_hybrid" if capabilities.get("hybrid") else "classical"
        server = {"experiment": {"mqtt": {"tls": {"mode": f"{mode_prefix}_tls_server_auth", "key_exchange_group": group, "server_signature_algorithm": "classical"}}}}
        mutual = {"experiment": {"mqtt": {"tls": {"mode": f"{mode_prefix}_tls_mutual", "key_exchange_group": group, "server_signature_algorithm": "classical"}}}}
        a = resolve_tls_algorithm_set(server)
        b = resolve_tls_algorithm_set(mutual)
        for key in ("group_token", "ecc", "ecc_bits", "curve25519", "mlkem_768", "mlkem_1024"):
            assert a[key] == b[key]


def test_all_mutual_profiles_declare_mutual_authentication():
    for group in TLS_GROUPS:
        path = Path("configs/experiments") / f"mqtt_tls_{group}_mutual_auth_st67_e2e.yaml"
        text = path.read_text(encoding="utf-8")
        assert _scalar(text, "authentication") == "mutual"
        assert _scalar(text, "broker_profile") in {"classical", "oqs-mtls"}
