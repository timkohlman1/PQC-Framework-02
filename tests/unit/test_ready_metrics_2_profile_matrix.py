from pathlib import Path

READY_METRICS_ROOT = Path("configs/experiments/applications/ready_metrics")
READY_METRICS_2_ROOT = Path("configs/experiments/applications/ready_metrics_2")


def _rm2_name(name: str) -> str:
    assert name.startswith("ready_metrics_")
    return name.replace("ready_metrics_", "ready_metrics_2_", 1)


def test_ready_metrics_2_matrix_clones_every_ready_metrics_profile():
    source_profiles = sorted(READY_METRICS_ROOT.glob("*.yaml"))
    cloned_profiles = sorted(READY_METRICS_2_ROOT.glob("ready_metrics_2_*.yaml"))

    assert source_profiles
    assert len(cloned_profiles) == len(source_profiles)

    missing = [
        READY_METRICS_2_ROOT / _rm2_name(source.name)
        for source in source_profiles
        if not (READY_METRICS_2_ROOT / _rm2_name(source.name)).is_file()
    ]
    assert not missing, "missing Ready Metrics 2 profiles:\n" + "\n".join(
        str(path) for path in missing
    )


def test_ready_metrics_2_matrix_selects_new_application_and_requested_wifi_password():
    for source in sorted(READY_METRICS_ROOT.glob("*.yaml")):
        clone = READY_METRICS_2_ROOT / _rm2_name(source.name)
        text = clone.read_text(encoding="utf-8")

        assert text.startswith("id: ready_metrics_2_")
        assert "application: mqtt_ready_metrics_2" in text
        assert "uart_log_level: info" in text
        assert "ssid: pqc" in text
        assert "psk: lukeisadog" in text
        assert "ttfb_start: immediately_before_lwip_connect_after_dns" in text
        assert (
            "ttfb_end: first_plaintext_byte_returned_while_receiving_mqtt_connack"
            in text
        )
        assert (
            "firmware_boot_origin: first_hal_tick_immediately_after_hal_init"
            in text
        )


def test_ready_metrics_2_matrix_preserves_crypto_and_broker_selection():
    preserved_prefixes = (
        "broker_profile:",
        "port:",
        "tls_version:",
        "mode:",
        "authentication:",
        "key_exchange_group:",
        "server_signature_algorithm:",
        "certificate_profile:",
    )

    for source in sorted(READY_METRICS_ROOT.glob("*.yaml")):
        clone = READY_METRICS_2_ROOT / _rm2_name(source.name)
        source_lines = {
            line.strip()
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(preserved_prefixes)
        }
        clone_lines = {
            line.strip()
            for line in clone.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith(preserved_prefixes)
        }
        assert source_lines <= clone_lines


def test_ready_metrics_2_runner_targets_only_ready_metrics_2_directory():
    source = Path("scripts/run_all_ready_metrics_2_profiles.py").read_text(
        encoding="utf-8"
    )
    assert '/ "ready_metrics_2"' in source
    assert '/ "ready_metrics"' not in source
    assert '"run"' in source
    assert '"--experiment"' in source
