from pathlib import Path

EXPERIMENT_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "experiment.py"


def test_hybrid_readiness_uses_detached_subscriber_and_log_polling():
    source = EXPERIMENT_SCRIPT.read_text(encoding="utf-8")
    readiness = source[source.index("def _wait_for_plaintext_mqtt_broker"):source.index("def _start_managed_mqtt_broker")]
    assert 'subscriber_name = "pqc-mqtt-readiness-sub"' in readiness
    assert 'docker run -d {container_options}' in readiness
    assert 'sleep 2;' in readiness
    assert 'subscriber_state=$(docker inspect' in readiness
    assert 'response=$(docker logs "$subscriber"' in readiness
    assert 'grep -Fx -- {message}' in readiness


def test_non_hybrid_readiness_retains_existing_probe_path():
    source = EXPERIMENT_SCRIPT.read_text(encoding="utf-8")
    assert "-m {message} -r" in source
    assert "-t {topic} -n -r" in source
    assert '-C 1 -W 4' in source


def test_hybrid_server_auth_profile_is_present():
    profile = Path(__file__).resolve().parents[2] / "configs" / "experiments" / "mqtt_tls_SecP256r1MLKEM768_server_auth_st67_e2e.yaml"
    assert profile.is_file()
