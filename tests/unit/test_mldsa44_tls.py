"""ML-DSA level selection must agree across resolver, compiler and evidence."""
from pathlib import Path
import subprocess
import pytest
from framework.config_resolver import ConfigResolver
from framework.tls_algorithms import TLS_GROUPS
from framework.build import _write_tls_algorithm_selection
from framework.tls_instrumentation import expected_tls_instrumentation_events
from framework.mldsa_sampling import extract_mldsa_sampling

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize("mode", ["server", "mutual"])
@pytest.mark.parametrize("group", list(TLS_GROUPS))
def test_mldsa44_is_exclusive_and_reaches_compiler_and_evidence(tmp_path, mode, group):
    import yaml
    data = yaml.safe_load((ROOT/"configs/campaigns/tls_authentication.yaml").read_text())
    data["fixed"]["tls_kex"] = group
    data["matrix"] = dict(tls_auth=["mldsa44"], auth_mode=[mode])
    path = tmp_path/"case.yaml"; path.write_text(yaml.safe_dump(data))
    resolver = ConfigResolver(ROOT)
    case, = resolver.expand_campaign(path)
    bundle = resolver.to_legacy_bundle(case, resolve_secrets=False)
    selection, flags = _write_tls_algorithm_selection(bundle, tmp_path/"build")
    assert flags["mldsa_44"] and flags["mldsa_44_sign"] == (mode == "mutual")
    assert not flags["mldsa_65"] and not flags["mldsa_65_sign"]
    assert flags["signature_schemes"] == ["mldsa44"]
    text = selection.read_text()
    assert "set(PQC_TLS_ENABLE_MLDSA_44 ON)" in text
    assert "set(PQC_TLS_ENABLE_MLDSA_65 OFF)" in text
    expected = expected_tls_instrumentation_events(bundle)
    assert "mldsa44_verify" in expected
    assert ("mldsa44_sign" in expected) == (mode == "mutual")
    assert not any(p.startswith("mldsa65") for p in expected)

@pytest.mark.parametrize("level", [44, 65])
@pytest.mark.parametrize("sign", [0, 1])
def test_preprocessor_enables_only_selected_parameter_set(level, sign):
    command = ["cc", "-E", "-dM", "-x", "c", "-", "-I"+str(ROOT/"Core/Inc"),
        f"-DPQC_TLS_ENABLE_MLDSA_{level}=1", f"-DPQC_TLS_ENABLE_MLDSA_{level}_SIGN={sign}"]
    macros = subprocess.check_output(command, input='#include "pqc_wolfssl_user_settings.h"\n', text=True)
    other = 65 if level == 44 else 44
    assert f"#define WOLFSSL_NO_ML_DSA_{level}" not in macros
    assert f"#define WOLFSSL_NO_ML_DSA_{other}" in macros
    assert "#define WOLFSSL_NO_ML_DSA_87" in macros
    assert ("#define WOLFSSL_MLDSA_VERIFY_ONLY" in macros) == (not sign)

@pytest.mark.parametrize("campaign", ["tls_authentication", "thesis_authentication"])
def test_authentication_grid_has_five_families_and_both_roles(campaign):
    cases = ConfigResolver(ROOT).expand_campaign(campaign)
    assert len(cases) == 10
    assert {(c["choices"]["tls_auth"], c["choices"]["auth_mode"]) for c in cases} == {
        (a, m) for a in ("rsa3072", "ecdsa-p256", "ecdsa-p384", "mldsa44", "mldsa65")
        for m in ("server", "mutual")}
