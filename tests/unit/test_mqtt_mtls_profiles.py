from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.config_resolver import ConfigResolver
from framework.tls_algorithms import TLS_GROUPS, resolve_tls_algorithm_set


def _mode_prefix(capabilities: dict) -> str:
    if capabilities.get("hybrid"):
        return "pqc_hybrid"
    if capabilities.get("standalone_mlkem"):
        return "pqc"
    return "classical"


def test_server_and_mutual_profiles_share_group_capabilities():
    for group, capabilities in TLS_GROUPS.items():
        mode_prefix = _mode_prefix(capabilities)
        server = {"experiment": {"mqtt": {"tls": {"mode": f"{mode_prefix}_tls_server_auth", "key_exchange_group": group, "server_signature_algorithm": "classical"}}}}
        mutual = {"experiment": {"mqtt": {"tls": {"mode": f"{mode_prefix}_tls_mutual", "key_exchange_group": group, "server_signature_algorithm": "classical"}}}}
        a = resolve_tls_algorithm_set(server)
        b = resolve_tls_algorithm_set(mutual)
        for key in ("group_token", "ecc", "ecc_bits", "curve25519", "mlkem_512", "mlkem_768", "mlkem_1024", "mlkem_standalone"):
            assert a[key] == b[key]


def test_tls_auth_profiles_support_mutual_without_per_group_profile_duplication():
    resolver = ConfigResolver(ROOT)
    cases = resolver.expand_campaign("tls_authentication")
    mutual_cases = [case for case in cases if case["choices"]["auth_mode"] == "mutual"]

    assert {case["choices"]["tls_auth"] for case in mutual_cases} == {
        "rsa3072", "ecdsa-p256", "ecdsa-p384", "mldsa65"
    }
    assert all(case["choices"]["tls_kex"] == "secp256r1" for case in mutual_cases)

    # The canonical model intentionally keeps authentication mode orthogonal to
    # TLS KEX and TLS authentication profiles rather than duplicating profile files.
    assert len(list((ROOT / "configs/tls_auth").glob("*.yaml"))) == 5
    for profile_id in ("rsa3072", "ecdsa-p256", "ecdsa-p384", "mldsa65"):
        profile = resolver.load_profile("tls_auth", profile_id).data
        assert "mutual" in profile["supported_modes"]
        assert "client" in profile["identities"]
