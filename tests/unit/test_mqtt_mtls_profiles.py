from pathlib import Path

from scripts.framework.tls_algorithms import resolve_tls_algorithm_set


def _bundle(mode: str):
    return {"experiment": {"mqtt": {"tls": {"mode": mode, "server_signature_algorithm": "classical"}}}}


def test_mtls_profiles_reuse_server_auth_algorithm_sets():
    classical_server = resolve_tls_algorithm_set(_bundle("classical_tls_server_auth"))
    classical_mutual = resolve_tls_algorithm_set(_bundle("classical_tls_mutual"))
    hybrid_server = resolve_tls_algorithm_set(_bundle("pqc_hybrid_tls_server_auth"))
    hybrid_mutual = resolve_tls_algorithm_set(_bundle("pqc_hybrid_tls_mutual"))
    assert {k: v for k, v in classical_server.items() if k != "mode"} == {k: v for k, v in classical_mutual.items() if k != "mode"}
    assert {k: v for k, v in hybrid_server.items() if k != "mode"} == {k: v for k, v in hybrid_mutual.items() if k != "mode"}


def test_mtls_experiment_profiles_are_parallel_to_server_auth_profiles():
    classical = Path("configs/experiments/mqtt_tls_mutual_auth_st67_e2e.yaml").read_text()
    hybrid = Path("configs/experiments/mqtt_tls_pqc_hybrid_mutual_auth_st67_e2e.yaml").read_text()
    assert "broker_profile: classical" in classical
    assert "mode: classical_tls_mutual" in classical
    assert "authentication: mutual" in classical
    assert "broker_profile: oqs-mtls" in hybrid
    assert "mode: pqc_hybrid_tls_mutual" in hybrid
    assert "key_exchange_group: SecP256r1MLKEM768" in hybrid
    assert "server_signature_algorithm: classical" in hybrid


def test_firmware_loads_client_identity_only_for_mutual_tls():
    source = Path("Core/Src/pqc_wolfmqtt_build_only.c").read_text()
    assert "PQC_WolfMQTT_MutualTLSRequested" in source
    assert "wolfSSL_CTX_use_certificate_buffer" in source
    assert "wolfSSL_CTX_use_PrivateKey_buffer" in source
    assert 'PQC_WolfMQTT_DiagnosticCode("client_certificate_load"' in source
    assert 'PQC_WolfMQTT_DiagnosticCode("client_private_key_load"' in source


def test_external_dependency_resolution_adds_mtls_inputs():
    source = Path("scripts/framework/external_dependencies.py").read_text()
    assert '"client_certificate"' in source
    assert '"client_private_key"' in source
    fingerprint = Path("scripts/framework/fingerprint.py").read_text()
    assert '("ca_certificate", "client_certificate", "client_private_key")' in fingerprint


def test_hybrid_mtls_broker_requires_client_certificate():
    config = Path("experiment/mqtt-broker/config/oqs-mtls/mosquitto.conf").read_text()
    compose = Path("experiment/mqtt-broker/compose.yaml").read_text()
    assert "require_certificate true" in config
    assert "use_identity_as_username true" in config
    assert "mqtt-oqs-mtls:" in compose
    assert 'profiles: ["oqs-mtls"]' in compose


def test_mtls_host_side_clients_present_client_identity_for_readiness_and_e2e():
    source = Path("scripts/experiment.py").read_text()
    assert "def _mqtt_gateway_tls_args(" in source
    assert 'args += " --cert /certs/client.crt --key /certs/client.key"' in source
    assert 'f" --cert {_mqtt_remote_client_certificate_file(bundle)}"' in source
    assert 'f" --key {_mqtt_remote_client_private_key_file(bundle)}"' in source
    assert source.count("_mqtt_gateway_tls_args(bundle, container_paths=True)") == 2
    assert source.count("_mqtt_gateway_tls_args(bundle, container_paths=False)") == 2


def test_server_auth_host_side_clients_do_not_unconditionally_add_client_identity():
    source = Path("scripts/experiment.py").read_text()
    helper = source[source.index("def _mqtt_gateway_tls_args("):source.index("def _mqtt_orchestration_host(")]
    assert helper.count("if _mqtt_mutual_tls_enabled(bundle):") == 2
    assert "authentication" in source[source.index("def _mqtt_mutual_tls_enabled("):source.index("def _mqtt_remote_client_certificate_file(")]
