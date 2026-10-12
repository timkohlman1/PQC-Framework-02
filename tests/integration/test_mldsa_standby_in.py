"""Real pinned keygen/sign tools with disposable multi-key tuples; no hardware."""
import os
import shutil
import subprocess
from pathlib import Path
import pytest
from framework import wolfboot_build as wb

ROOT = Path(__file__).resolve().parents[2]
pytestmark=pytest.mark.integration


def test_real_multikey_mldsa_levels_sign_without_replacing_tuple(tmp_path,pqc_require_capabilities):
    pqc_require_capabilities("local_toolchain",strict_mode="local_build")
    tools = ROOT / "tools/wolfboot/tools/keytools"
    built = subprocess.run(["make","-C",str(tools),"-j2"],capture_output=True,text=True)
    assert built.returncode == 0, built.stdout+built.stderr
    source = tmp_path / "tools/wolfboot"
    (source/"tools/keytools").mkdir(parents=True)
    (source/"src").mkdir()
    (source/"include").mkdir()
    for name in ("keygen","sign"): shutil.copy2(tools/name,source/"tools/keytools"/name)
    (source/"Makefile").write_text("keytools:\n\t@test -x tools/keytools/keygen\n")
    for algorithm,(level,size) in wb.ML_DSA_TUPLE_PARAMETERS.items():
        profile={"signature_algorithm":algorithm,"build":{
            "standby_keygen_option":"--ml_dsa","signing_tuple":{
                "directory":"tuples/"+algorithm,"standby_private_keys":["standby_key_1.der","standby_key_2.der"]}}}
        paths=wb._signing_tuple_paths(profile=profile,repo_root=tmp_path,source_dir=source)
        error=wb._create_multi_key_persistent_tuple(profile=profile,paths=paths,source_dir=source)
        assert error is None,error
        assert wb._load_and_validate_persistent_tuple(profile=profile,paths=paths)==("complete",None)
        before={p:p.read_bytes() for p in paths["directory"].iterdir()}
        for index,name in enumerate(("private_key","standby_private_key_1","standby_private_key_2")):
            assert paths[name].stat().st_size==size
            payload=tmp_path/f"{algorithm}-{index}.bin";payload.write_bytes(b"example firmware payload"*32)
            signed=subprocess.run([str(source/"tools/keytools/sign"),"--ml_dsa",str(payload),str(paths[name]),"1"],
                cwd=source,env=dict(os.environ,ML_DSA_LEVEL=str(level),IMAGE_HEADER_SIZE="8192"),capture_output=True,text=True)
            assert signed.returncode==0,signed.stdout+signed.stderr
            assert payload.with_name(payload.stem+"_v1_signed.bin").is_file()
        assert all(p.read_bytes()==value for p,value in before.items())
