from pathlib import Path
import os
import sys
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from framework.config_resolver import ConfigResolver, ResolutionError, render_wolfboot_config


def test_tls_key_exchange_campaign_has_ten_thesis_groups():
    cases = ConfigResolver(ROOT).expand_campaign('tls_key_exchange')
    assert [c['choices']['tls_kex'] for c in cases] == [
        'x25519','secp256r1','secp384r1','secp521r1','X25519MLKEM768',
        'SecP256r1MLKEM768','SecP384r1MLKEM1024','ML_KEM_512','ML_KEM_768','ML_KEM_1024'
    ]


def test_ready_metrics_2_defaults_and_overrides_are_resolved_without_profile_duplication(tmp_path):
    resolver = ConfigResolver(ROOT)
    campaign = yaml.safe_load((ROOT/'configs/campaigns/ready_metrics_2.yaml').read_text())
    campaign['matrix'] = {'workload.transfer.payload_bytes':[204800,409600], 'workload.transfer.chunk_bytes':[400,800]}
    p=tmp_path/'campaign.yaml'; p.write_text(yaml.safe_dump(campaign, sort_keys=False))
    cases=resolver.expand_campaign(p)
    assert len(cases)==4
    assert {(c['choices']['payload_bytes'], c['choices']['chunk_bytes']) for c in cases} == {(204800,400),(204800,800),(409600,400),(409600,800)}
    assert all(c['selections']['workload']=='ready_metrics_2' for c in cases)


def test_standalone_mlkem_is_not_hybrid():
    resolver=ConfigResolver(ROOT)
    kex=resolver.load_profile('tls_kex','ML_KEM_768').data
    assert kex['class']=='standalone_pqc'
    assert kex['wolfssl']['standalone_mlkem_tls'] is True
    assert not kex['wolfssl'].get('pqc_hybrids',False)




def test_gateway_profile_declares_fqdn_for_remote_orchestration():
    resolver = ConfigResolver(ROOT)
    gateway = resolver.load_profile('gateway', 'pqc_gateway1').data
    assert gateway['identity']['alias'] == 'pqc-gateway1'
    assert gateway['identity']['fqdn'] == 'pqc-gateway1.pqcnet'

def test_reporting_broker_is_plaintext_and_impairment_exempt():
    resolver=ConfigResolver(ROOT)
    broker=resolver.load_service('mqtt_broker','reporting_gateway1').data
    assert broker['transport']=='plaintext'
    assert broker['tls']['enabled'] is False
    assert broker['tls']['pki_required'] is False
    assert broker['network']['impairment_exempt'] is True


def _assert_rendered_wolfboot_contains(rendered: str, key: str, value):
    if isinstance(value, list):
        for item in value:
            assert str(item) in rendered
        return
    assert f"{key}={value}" in rendered


def test_generated_wolfboot_configs_are_composed_from_canonical_profiles():
    resolver = ConfigResolver(ROOT)
    target = resolver.load_profile("target", "stm32l4r5_st67").data
    secure_boot_ids = [
        "integrity_sha256", "ecdsa_p256", "ecdsa_p384", "ecdsa_p521",
        "ed25519", "ed448", "rsa2048", "rsa3072", "rsa4096",
        "mldsa44", "mldsa65", "mldsa87",
    ]
    for ident in secure_boot_ids:
        profile = resolver.load_profile("secure_boot", ident).data
        rendered = render_wolfboot_config(target, profile)
        for key, value in target["wolfboot"]["config"].items():
            _assert_rendered_wolfboot_contains(rendered, key, value)
        for key, value in profile["wolfboot"]["config"].items():
            _assert_rendered_wolfboot_contains(rendered, key, value)


def test_generated_case_materialization_is_compact_and_stable(tmp_path):
    resolver=ConfigResolver(ROOT)
    root=resolver.materialize_campaign('ready_metrics_2', tmp_path/'out')
    case_path=next((root/'cases').glob('*.yaml'))
    case=yaml.safe_load(case_path.read_text())
    assert case['kind']=='resolved_case'
    assert 'target' not in case or not isinstance(case.get('target'), dict)
    assert case['selections']['target']=='stm32l4r5_st67'
    assert len(case['provenance']['configuration_identity'])==64
    assert resolver.load_resolved_case(case_path)['provenance']['configuration_identity']==case['provenance']['configuration_identity']


def test_execution_bundle_resolves_secret_refs_only_in_memory(monkeypatch):
    monkeypatch.setenv('PQC_WIFI_SSID','test-ssid'); monkeypatch.setenv('PQC_WIFI_PSK','test-psk')
    resolver=ConfigResolver(ROOT); case=resolver.expand_campaign('ready_metrics_2')[0]
    bundle=resolver.to_legacy_bundle(case)
    assert bundle['experiment']['network']['wifi']=={'ssid':'test-ssid','psk':'test-psk'}
    assert case.get('network',{}).get('wifi') is None
    assert bundle['experiment']['mqtt']['transfer']['payload_bytes']==204800
    assert bundle['experiment']['mqtt']['transfer']['chunk_bytes']==400
    assert bundle['experiment']['mqtt']['tls']['mode']=='pqc_tls_server_auth'


def test_tls_pq_only_campaign_has_server_and_mutual_mldsa65_mlkem768_cases():
    cases = ConfigResolver(ROOT).expand_campaign('tls_pq_only')
    assert len(cases) == 2
    assert [c['choices']['auth_mode'] for c in cases] == ['server', 'mutual']
    assert all(c['choices']['tls_kex'] == 'ML_KEM_768' for c in cases)
    assert all(c['choices']['tls_auth'] == 'mldsa65' for c in cases)
    assert all(c['choices']['secure_boot'] == 'integrity_sha256' for c in cases)
    assert all(c['choices']['network_condition'] == 'baseline' for c in cases)

def test_secure_boot_campaign_uses_runnable_mqtt_validation_workload(monkeypatch):
    monkeypatch.setenv('PQC_WIFI_SSID', 'test-ssid')
    monkeypatch.setenv('PQC_WIFI_PSK', 'test-psk')
    resolver = ConfigResolver(ROOT)
    cases = resolver.expand_campaign('secure_boot')
    assert len(cases) == 12
    assert all(c['selections']['workload'] == 'mqtt_validation' for c in cases)
    bundle = resolver.to_legacy_bundle(cases[0])
    assert bundle['experiment']['firmware']['application'] == 'mqtt_validation'



def test_materialize_campaign_removes_stale_generated_case_files(tmp_path):
    resolver = ConfigResolver(ROOT)
    output = tmp_path / "generated"
    root = resolver.materialize_campaign("baseline", output)
    cases_dir = root / "cases"
    stale = cases_dir / "0000_stale.yaml"
    stale.write_text("kind: resolved_case\n", encoding="utf-8")
    assert stale.exists()

    resolver.materialize_campaign("baseline", output)

    assert not stale.exists()
    materialized = sorted(cases_dir.glob("*.yaml"))
    assert materialized
    assert all(resolver.load_resolved_case(path)["kind"] == "resolved_case" for path in materialized)


def test_tls_handshake_repeat_profile_has_explicit_independent_iteration_semantics():
    resolver = ConfigResolver(ROOT)
    workload = resolver.load_profile("workload", "tls_handshake_repeat").data
    assert workload["firmware_application"] == "tls_handshake_repeat"
    assert workload["iterations"] == {
        "handshakes_per_run": 10,
        "reset_between_handshakes": False,
        "fresh_tcp_connection": True,
        "fresh_tls_context": True,
        "session_resumption": False,
    }
    assert workload["evidence"]["reporting_epoch"] == "per_handshake_post_measurement"


def test_tls_handshake_repeat_bundle_preserves_iteration_count_when_campaign_exists(monkeypatch):
    campaign_path = ROOT / "configs" / "campaigns" / "tls_handshake_repeat.yaml"
    if not campaign_path.is_file():
        import pytest
        pytest.skip("tls_handshake_repeat campaign is not present in this repository state")
    monkeypatch.setenv("PQC_WIFI_SSID", "test-ssid")
    monkeypatch.setenv("PQC_WIFI_PSK", "test-psk")
    resolver = ConfigResolver(ROOT)
    case = resolver.expand_campaign("tls_handshake_repeat")[0]
    bundle = resolver.to_legacy_bundle(case)
    expected = int(bundle["experiment"]["workload"]["iterations"]["handshakes_per_run"])
    assert expected >= 1
    assert bundle["experiment"]["firmware"]["application"] == "tls_handshake_repeat"
    assert bundle["experiment"]["mqtt"]["orchestration"]["expected_stm32_result_epochs"] == expected


def test_plaintext_mqtt_campaign_resolves_without_tls_or_secret_resolution(tmp_path):
    resolver = ConfigResolver(ROOT)
    case = resolver.expand_campaign("mqtt_plaintext_validation")[0]
    assert case["choices"]["mqtt_transport"] == "plaintext"
    mqtt = resolver.to_legacy_bundle(case, resolve_secrets=False)["experiment"]["mqtt"]
    assert mqtt["evidence_class"] == "stm32_st67_plaintext_e2e"
    assert mqtt["transport_backend"] == "st67w61m1_lwip_sockets"
    assert mqtt["broker_profile"] == "classical"
    assert mqtt["broker"]["port"] == 1883
    assert mqtt["tls"]["mode"] == "plaintext"
    assert "certificate_profile" not in mqtt["tls"]
    assert resolver.load_resolved_case(
        next(resolver.materialize_campaign("mqtt_plaintext_validation", tmp_path / "cases-root").joinpath("cases").glob("*.yaml"))
    )["provenance"]["configuration_identity"] == case["provenance"]["configuration_identity"]


def test_plaintext_mqtt_rejects_incompatible_transport_choices():
    resolver = ConfigResolver(ROOT)
    case = resolver.expand_campaign("mqtt_plaintext_validation")[0]
    for update, expected in (
        ({"auth_mode": "mutual"}, "mutual TLS"),
        ({"mqtt_transport": "invalid"}, "mqtt_transport"),
    ):
        with __import__("pytest").raises(ResolutionError, match=expected):
            resolver.resolve_case(
                campaign_id="invalid-plaintext", case_index=1,
                selections=case["selections"], choices={**case["choices"], **update},
                workload_overrides={}, execution=case["execution"],
            )


def test_plaintext_mqtt_rejects_non_validation_workload():
    resolver = ConfigResolver(ROOT)
    case = resolver.expand_campaign("mqtt_plaintext_validation")[0]
    with __import__("pytest").raises(ResolutionError, match="mqtt_validation workload"):
        resolver.resolve_case(
            campaign_id="invalid-workload", case_index=1,
            selections={**case["selections"], "workload": "ready_metrics"},
            choices=case["choices"], workload_overrides={}, execution=case["execution"],
        )


def test_secure_boot_uart_diagnostics_default_off_and_affects_firmware_identity(tmp_path):
    resolver = ConfigResolver(ROOT)
    _, campaign = resolver.load_campaign("secure_boot")
    base = dict(campaign["fixed"])
    assert base.get("boot_uart_diagnostics") is False

    selected = {
        "target": campaign["target"],
        "gateway": campaign["gateway"],
        "services": campaign["services"],
        "workload": campaign["workload"],
    }
    normal = resolver.resolve_case(
        campaign_id="diag_test", case_index=1, selections=selected, choices={**base, "secure_boot": "integrity_sha256"},
        workload_overrides={}, execution=campaign["execution"],
    )
    diagnostic = resolver.resolve_case(
        campaign_id="diag_test", case_index=2, selections=selected,
        choices={**base, "secure_boot": "integrity_sha256", "boot_uart_diagnostics": True},
        workload_overrides={}, execution=campaign["execution"],
    )
    assert normal["choices"]["boot_uart_diagnostics"] is False
    assert diagnostic["choices"]["boot_uart_diagnostics"] is True
    assert normal["provenance"]["firmware_identity"] != diagnostic["provenance"]["firmware_identity"]


def test_secure_boot_uart_diagnostics_must_be_boolean():
    resolver = ConfigResolver(ROOT)
    _, campaign = resolver.load_campaign("secure_boot")
    choices = dict(campaign["fixed"])
    choices.update({"secure_boot": "integrity_sha256", "boot_uart_diagnostics": "yes"})
    selected = {
        "target": campaign["target"], "gateway": campaign["gateway"],
        "services": campaign["services"], "workload": campaign["workload"],
    }
    with pytest.raises(ResolutionError, match="boot_uart_diagnostics must be a boolean"):
        resolver.resolve_case(campaign_id="diag_bad", case_index=1, selections=selected, choices=choices, workload_overrides={}, execution=campaign["execution"])
