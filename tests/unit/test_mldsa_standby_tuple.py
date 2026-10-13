"""Protect the selected ML-DSA level and immutable canonical tuple identity."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from framework import wolfboot_build as wb
from experiment import load_secure_boot_profile_section

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("algorithm,level,size", [("mldsa44",2,3872),("mldsa65",3,5984),("mldsa87",5,7488)])
def test_multi_key_generation_uses_selected_level_and_preserves_tuple(tmp_path, monkeypatch, algorithm, level, size):
    source = tmp_path / "tools/wolfboot"
    (source / "tools/keytools").mkdir(parents=True)
    (source / "tools/keytools/keygen").touch()
    (source / "src").mkdir()
    profile = {"signature_algorithm":algorithm,"build":{
        "standby_keygen_option":"--ml_dsa",
        "signing_tuple":{"directory":"tuple","standby_private_keys":["standby_key_1.der"]}}}
    paths = wb._signing_tuple_paths(profile=profile,repo_root=tmp_path,source_dir=source)
    def execute(command, **kwargs):
        if command[0] != "make":
            assert kwargs["env"]["ML_DSA_LEVEL"] == str(level)
            for index, part in enumerate(command):
                if part == "-g": Path(command[index+1]).write_bytes(b"k"*size)
            paths["materialized_keystore"].write_text("public keystore")
        return SimpleNamespace(returncode=0,stdout="",stderr="")
    monkeypatch.setenv("ML_DSA_LEVEL","2")
    monkeypatch.setattr(wb.subprocess,"run",execute)
    assert wb._create_multi_key_persistent_tuple(profile=profile,paths=paths,source_dir=source) is None
    assert wb._load_and_validate_persistent_tuple(profile=profile,paths=paths) == ("complete",None)
    old = {p:p.read_bytes() for p in paths["directory"].iterdir()}
    # Hash-consistent metadata cannot turn a level-2 key into a level-3 key.
    if algorithm == "mldsa65":
        paths["private_key"].write_bytes(b"k"*3872)
        manifest = json.loads(paths["manifest"].read_text())
        manifest["private_key_sha256"] = wb._tuple_sha256(paths["private_key"])
        paths["manifest"].write_text(json.dumps(manifest))
        old = {p:p.read_bytes() for p in paths["directory"].iterdir()}
        status, reason = wb._load_and_validate_persistent_tuple(profile=profile,paths=paths)
        assert status == "incompatible" and "raw key size" in reason
        assert all(p.read_bytes()==data for p,data in old.items())


@pytest.mark.parametrize("algorithm,level",[("mldsa65",3),("mldsa87",5)])
def test_corrected_standby_identity_does_not_replace_existing_single_key(algorithm,level):
    normal,_ = load_secure_boot_profile_section(target_profile=ROOT/"configs/targets/stm32l4r5_wolfboot.yaml",algorithm=algorithm,section="build")
    multi,_ = load_secure_boot_profile_section(target_profile=ROOT/"configs/targets/stm32l4r5_wolfboot.yaml",algorithm=algorithm,section="build",standby_signing_keys=2)
    signing,_ = load_secure_boot_profile_section(target_profile=ROOT/"configs/targets/stm32l4r5_wolfboot.yaml",algorithm=algorithm,section="signing",standby_signing_keys=2)
    assert normal["build"]["signing_tuple"]["tuple_id"] == algorithm+"-development"
    assert multi["build"]["signing_tuple"]["tuple_id"] == f"{algorithm}-development-level{level}-standby2"
    assert signing["private_key"] == multi["build"]["signing_key"]
