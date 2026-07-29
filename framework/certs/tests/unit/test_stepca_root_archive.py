from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    script = Path(__file__).resolve().parents[2] / "services" / "stepca-root" / "archive_root.py"
    spec = importlib.util.spec_from_file_location("archive_root", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publish_public_material_writes_root_intermediate_and_chain(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "PUBLIC_DIR", tmp_path)

    module.publish_public_material("ROOT\n", "INTERMEDIATE\n")

    assert (tmp_path / "root-ca.crt").read_text() == "ROOT\n"
    assert (tmp_path / "intermediate-ca.crt").read_text() == "INTERMEDIATE\n"
    assert (tmp_path / "ca.crt").read_text() == "ROOT\n"
    assert (tmp_path / "ca-chain.crt").read_text() == "INTERMEDIATE\nROOT\n"


def test_main_archives_then_removes_online_root_key(tmp_path, monkeypatch):
    module = _module()
    stepca = tmp_path / "stepca"
    state = tmp_path / "state"
    public = tmp_path / "public"
    (stepca / "certs").mkdir(parents=True)
    (stepca / "secrets").mkdir(parents=True)
    state.mkdir()

    root_cert = stepca / "certs" / "root_ca.crt"
    root_key = stepca / "secrets" / "root_ca_key"
    intermediate = stepca / "certs" / "intermediate_ca.crt"
    token_file = state / "root.token"
    root_cert.write_text("ROOT CERT\n")
    root_key.write_text("ROOT KEY\n")
    intermediate.write_text("INTERMEDIATE CERT\n")
    token_file.write_text("token")

    monkeypatch.setattr(module, "ROOT_CERT", root_cert)
    monkeypatch.setattr(module, "ROOT_KEY", root_key)
    monkeypatch.setattr(module, "INTERMEDIATE_CERT", intermediate)
    monkeypatch.setattr(module, "ROOT_TOKEN_FILE", token_file)
    monkeypatch.setattr(module, "PUBLIC_DIR", public)
    monkeypatch.setattr(module, "read_existing", lambda token: None)

    captured = {}

    def write_record(token, root_cert_text, root_key_text, intermediate_text):
        captured.update(
            token=token,
            root_cert=root_cert_text,
            root_key=root_key_text,
            intermediate=intermediate_text,
        )

    monkeypatch.setattr(module, "write_root_record", write_record)

    assert module.main() == 0
    assert captured["token"] == "token"
    assert captured["root_key"] == "ROOT KEY\n"
    assert not root_key.exists()
    assert (public / "root-ca.crt").is_file()
