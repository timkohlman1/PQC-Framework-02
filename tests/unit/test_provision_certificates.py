from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "provision_certificates.py"
CONFIG_DIR = REPO_ROOT / "configs" / "tls_auth"


def _load_module():
    spec = importlib.util.spec_from_file_location("provision_certificates", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_certificate_profiles_are_config_driven():
    module = _load_module()
    profiles = module.load_profiles(CONFIG_DIR)
    assert [profile.profile_id for profile in profiles] == [
        "ecdsa-p256", "ecdsa-p384", "ed25519", "mldsa65", "rsa3072"
    ]
    assert not hasattr(module, "FAMILIES")


def test_profile_ids_match_filenames_and_define_complete_tls_roles():
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert profile["id"] == path.stem
        assert profile["hierarchy"]["intermediate"] is True
        assert set(profile["identities"]) == {"server", "client", "healthcheck"}
        assert profile["identities"]["server"]["extended_key_usage"] == ["serverAuth"]
        assert profile["identities"]["client"]["extended_key_usage"] == ["clientAuth"]
        assert profile["identities"]["healthcheck"]["extended_key_usage"] == ["clientAuth"]


def test_profiles_define_long_lived_certificate_validity():
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        profile = yaml.safe_load(path.read_text(encoding="utf-8"))
        validity = profile["certificate"]["validity_days"]
        assert validity == {"root": 7300, "intermediate": 5475, "leaf": 3650}


def test_profile_parser_rejects_id_filename_mismatch(tmp_path: Path):
    module = _load_module()
    source = yaml.safe_load((CONFIG_DIR / "rsa3072.yaml").read_text(encoding="utf-8"))
    source["id"] = "wrong-id"
    path = tmp_path / "rsa3072.yaml"
    path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="must match filename"):
        module.load_profile(path)


def test_default_paths_are_repository_config_and_root_secrets():
    module = _load_module()
    args = module.build_parser().parse_args([])
    assert Path(args.config_dir) == REPO_ROOT / "configs" / "tls_auth"
    assert Path(args.output) == REPO_ROOT / "secrets" / "certificates"
    assert module.DOCKER_IMAGE == "alpine:3.23@sha256:fd791d74b68913cbb027c6546007b3f0d3bc45125f797758156952bc2d6daf40"


def test_pqc_container_does_not_force_local_openssl(monkeypatch):
    module = _load_module()
    calls = []
    monkeypatch.setenv("PQC_CONTAINER", "1")
    monkeypatch.setattr(module, "provision_with_docker", lambda args: calls.append("docker"))
    monkeypatch.setattr(module, "provision_local", lambda args: calls.append("local"))
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH)])
    assert module.main() == 0
    assert calls == ["docker"]


def test_local_openssl_is_explicit_opt_in(monkeypatch):
    module = _load_module()
    calls = []
    monkeypatch.setenv("PQC_CONTAINER", "1")
    monkeypatch.setattr(module, "provision_with_docker", lambda args: calls.append("docker"))
    monkeypatch.setattr(module, "provision_local", lambda args: calls.append("local"))
    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "--local-openssl"])
    assert module.main() == 0
    assert calls == ["local"]


def test_ci_provisions_certificates_from_host_into_pinned_runtime():
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "run: python scripts/provision_certificates.py" in workflow
    assert "./scripts/dev.sh python scripts/provision_certificates.py" not in workflow



def test_local_provisioning_refuses_root_before_generating_or_replacing(monkeypatch, tmp_path):
    module = _load_module()
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.os, "getuid", lambda: 0)
    monkeypatch.setattr(module, "load_profiles", lambda *args: pytest.fail("must refuse before reading profiles"))
    args = module.build_parser().parse_args(["--output", str(tmp_path / "certs"), "--force", "--local-openssl"])
    with pytest.raises(SystemExit, match="Refusing root certificate generation"):
        module.provision_local(args)
    assert not (tmp_path / "certs").exists()
