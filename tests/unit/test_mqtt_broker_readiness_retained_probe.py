from pathlib import Path

EXPERIMENT_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "experiment.py"


def test_pqc_readiness_uses_retained_publish_then_foreground_subscribe():
    source = EXPERIMENT_SCRIPT.read_text(encoding="utf-8")
    readiness = source[source.index("def _wait_for_plaintext_mqtt_broker"):source.index("def _start_managed_mqtt_broker")]
    pqc_branch = readiness[readiness.index("if pqc_oqs:"):readiness.index("    else:", readiness.index("if pqc_oqs:"))]
    assert 'docker run -d {container_options}' not in pqc_branch
    assert 'docker inspect' not in pqc_branch
    assert 'docker logs' not in pqc_branch
    assert '--entrypoint mosquitto_pub' in pqc_branch
    assert '-m {message} -r' in pqc_branch
    assert '--entrypoint mosquitto_sub' in pqc_branch
    assert '-C 1 -W 4' in pqc_branch
    assert 'response=$(paste -sd, "$response_file"' in pqc_branch
    assert '[ "$sub_rc" -eq 0 ] && [ "$pub_rc" -eq 0 ]' in pqc_branch
    assert '-n -r >/dev/null 2>&1 || true' in pqc_branch


def test_non_hybrid_readiness_retains_existing_probe_path():
    source = EXPERIMENT_SCRIPT.read_text(encoding="utf-8")
    assert "-m {message} -r" in source
    assert "-t {topic} -n -r" in source
    assert '-C 1 -W 4' in source


def test_hybrid_server_auth_profile_is_present():
    profile = Path(__file__).resolve().parents[2] / "configs" / "experiments" / "mqtt_tls_SecP256r1MLKEM768_server_auth_st67_e2e.yaml"
    assert profile.is_file()
