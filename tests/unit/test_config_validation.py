from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def load_experiment_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts" / "experiment.py"
    spec = importlib.util.spec_from_file_location("experiment_cli", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_validate_experiment_config_rejects_missing_board():
    experiment_cli = load_experiment_module()

    config = {
        "id": "baseline_direct_uart",
        "description": "Missing board field.",
        "host": "gateway",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Release/stm32_basic_hal1.elf",
        },
        "uart": {
            "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
            "expected_tick_message": "tick",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="board"):
        experiment_cli.validate_experiment_config(config)



def test_validate_experiment_config_rejects_missing_boot():
    experiment_cli = load_experiment_module()

    config = {
        "id": "baseline_direct_uart",
        "description": "Missing boot field.",
        "board": "board_a",
        "host": "gateway",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Release/stm32_basic_hal1.elf",
        },
        "uart": {
            "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
            "expected_tick_message": "tick",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="boot"):
        experiment_cli.validate_experiment_config(config)


def test_validate_boot_config_rejects_non_runnable_boot_profile():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
    }

    with pytest.raises(experiment_cli.ConfigError, match="planned and not runnable"):
        experiment_cli.validate_boot_config(config)


def test_validate_boot_config_for_inspection_accepts_planned_boot_profile():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
        "status": "planned",
        "intended_signature_algorithm": "ecdsa_p256",
        "application_slot_concept": "planned_signed_application_slot",
    }

    experiment_cli.validate_boot_config_for_inspection(config)

def test_validate_board_config_rejects_missing_stlink_serial():
    experiment_cli = load_experiment_module()

    config = {
        "id": "board_a",
        "name": "NUCLEO-L4R5ZI-P",
        "mcu": "STM32L4R5",
        "description": "Missing ST-LINK serial.",
        "stlink": {},
        "uart": {
            "baud": 115200,
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="stlink.serial"):
        experiment_cli.validate_board_config(config)


def test_validate_host_config_rejects_missing_uart_device():
    experiment_cli = load_experiment_module()

    config = {
        "id": "gateway",
        "alias": "pqc-gateway1",
        "user": "timk",
        "description": "Missing UART device.",
        "flash": {
            "helper": "flash-stm32a",
        },
        "uart": {
            "baud": 115200,
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="uart.device"):
        experiment_cli.validate_host_config(config)






def test_validate_boot_config_for_inspection_accepts_planned_flash_layout_metadata():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
        "status": "planned",
        "implementation_state": "secure_boot_flash_layout_defined_placeholder_only",
        "intended_signature_algorithm": "ecdsa_p256",
        "application_slot_concept": "planned_signed_application_primary_slot",
        "flash_layout_status": "defined_phase_10d_planned_not_implemented",
        "secure_boot_layout": {
            "status": "planned_not_runnable",
            "decision_record": "docs/decisions/0003_secure_boot_flash_layout.md",
            "internal_flash_base": "0x08000000",
            "internal_flash_size": "0x00200000",
            "internal_flash_end": "0x081FFFFF",
            "wolfboot_base": "0x08000000",
            "wolfboot_size": "0x00020000",
            "primary_slot_base": "0x08020000",
            "primary_slot_size": "0x000E0000",
            "primary_slot_entry": "0x08023000",
            "image_header_size": "0x00002000",
            "update_slot_base": "0x08100000",
            "update_slot_size": "0x000E0000",
            "swap_metadata_base": "0x081E0000",
            "swap_metadata_size": "0x00020000",
            "sector_size_assumption": "0x00004000",
            "physical_flash_page_assumption": "0x00001000",
            "wolfboot_partition_boot_address": "0x08020000",
            "wolfboot_partition_size": "0x000E0000",
            "wolfboot_partition_update_address": "0x08100000",
            "wolfboot_partition_swap_address": "0x081E0000",
        },
    }

    experiment_cli.validate_boot_config_for_inspection(config)



def test_validate_boot_config_still_rejects_planned_flash_layout_for_execution():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_ecdsa_p256",
        "mode": "wolfboot_ecdsa_p256",
        "description": "Planned wolfBoot test boot config.",
        "runnable": False,
        "status": "planned",
        "flash_layout_status": "defined_phase_10d_planned_not_implemented",
        "secure_boot_layout": {
            "primary_slot_base": "0x08020000",
            "primary_slot_entry": "0x08023000",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="planned and not runnable"):
        experiment_cli.validate_boot_config(config)



def test_validate_application_signing_profile_accepts_ed25519_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_image": "build/Release/stm32_basic_hal1.bin",
        "signed_image": "build/Release/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "ed25519",
        "image_version": 1,
        "private_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
        "sign": {
            "command": "tools/wolfboot/tools/keytools/sign",
        },
    }

    experiment_cli.validate_application_signing_profile_config(config)


def test_validate_application_signing_profile_requires_keygen_command_when_enabled():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_image": "build/Release/stm32_basic_hal1.bin",
        "signed_image": "build/Release/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "ecdsa_p256",
        "image_version": 1,
        "private_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
        "keygen": {
            "enabled": True,
        },
        "sign": {
            "command": "tools/wolfboot/tools/keytools/sign",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="keygen.command"):
        experiment_cli.validate_application_signing_profile_config(config)


def test_validate_application_signing_profile_requires_binary_conversion_command_when_enabled():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_elf": "build/Release/stm32_basic_hal1.elf",
        "input_image": "build/Release/stm32_basic_hal1.bin",
        "signed_image": "build/Release/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "ecdsa_p256",
        "image_version": 1,
        "private_key": "secrets/wolfboot/ecdsa_p256_private_key.der",
        "binary_conversion": {
            "enabled": True,
        },
        "sign": {
            "command": "tools/wolfboot/tools/keytools/sign",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="binary_conversion.command"):
        experiment_cli.validate_application_signing_profile_config(config)


def _valid_classical_profile_model() -> dict[str, object]:
    return {
        "id": "secure_boot_signing", "description": "Secure-boot signing benchmark suite.",
        "schema_version": 2, "benchmark_scope": "secure_boot_signing_algorithm",
        "reference_algorithm": "ecdsa_p256",
        "minimum_algorithms": {"ed25519": True, "ecdsa_p256": True, "rsa2048": True},
        "expanded_algorithms": {"ecc384": True, "ecc521": True, "ed448": True, "rsa3072": True, "rsa4096": True},
        "post_quantum_algorithms": {"mldsa44": True, "mldsa65": True, "mldsa87": True},
        "unavailable_algorithms": {},
        "common_evidence": {
            "board": "board_a", "application_payload": "same_relocated_hal_application_payload",
            "measurement_method": "uart_explicit_wolfboot_mailbox_markers",
            "repeated_run_model": "phase_11_2_repeat_count_samples",
            "static_metrics_model": "phase_11_3_elf_and_artifact_metrics",
            "runtime_memory_model": "phase_11_4_firmware_side_stack_high_water_marker",
        },
    }


def test_validate_classical_profile_model_accepts_consolidated_suite():
    experiment_cli = load_experiment_module()
    experiment_cli.validate_classical_benchmark_profile_model_config(_valid_classical_profile_model())


def test_validate_classical_profile_model_rejects_missing_minimum_algorithm():
    experiment_cli = load_experiment_module(); config = _valid_classical_profile_model()
    config["minimum_algorithms"] = {"ed25519": True, "ecdsa_p256": True}
    with pytest.raises(experiment_cli.ConfigError, match="minimum_algorithms must contain exactly"):
        experiment_cli.validate_classical_benchmark_profile_model_config(config)


def test_validate_classical_profile_model_rejects_disabled_algorithm():
    experiment_cli = load_experiment_module(); config = _valid_classical_profile_model()
    config["expanded_algorithms"]["ecc384"] = False
    with pytest.raises(experiment_cli.ConfigError, match="values must all be true"):
        experiment_cli.validate_classical_benchmark_profile_model_config(config)


def test_validate_classical_profile_model_rejects_changed_reference_algorithm():
    experiment_cli = load_experiment_module(); config = _valid_classical_profile_model()
    config["reference_algorithm"] = "ed25519"
    with pytest.raises(experiment_cli.ConfigError, match="must remain ecdsa_p256"):
        experiment_cli.validate_classical_benchmark_profile_model_config(config)


def test_validate_classical_profile_model_rejects_runnable_unavailable_overlap():
    experiment_cli = load_experiment_module(); config = _valid_classical_profile_model()
    config["unavailable_algorithms"] = {"mldsa65": {"reason": "Invalid overlap."}}
    with pytest.raises(experiment_cli.ConfigError, match="must not also be runnable"):
        experiment_cli.validate_classical_benchmark_profile_model_config(config)


def test_validate_application_signing_profile_rejects_unsupported_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_test_signing",
        "description": "Invalid signing profile.",
        "input_image": "build/Release/stm32_basic_hal1.bin",
        "signed_image": "build/Release/stm32_basic_hal1_v1_signed.bin",
        "signature_algorithm": "sphincsplus",
        "image_version": 1,
        "private_key": "secrets/wolfboot/sphincsplus_private_key.der",
        "sign": {"command": "tools/wolfboot/tools/keytools/sign"},
    }

    with pytest.raises(
        experiment_cli.ConfigError,
        match="integrity_sha256, ecdsa_p256, ed25519, rsa2048, ecc384, ecc521, ed448, rsa3072, rsa4096, mldsa44, mldsa65, or mldsa87",
    ):
        experiment_cli.validate_application_signing_profile_config(config)


def test_validate_wolfboot_build_profile_accepts_ed25519_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_stm32l4_ed25519",
        "description": "ED25519 build profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "ed25519",
        "boot_profile": "wolfboot_ed25519",
        "build": {
            "command": "make",
            "config_template": "testdata/wolfboot/stm32l4r5_ed25519.config",
            "generated_config": "tools/wolfboot/.config",
        },
    }

    experiment_cli.validate_wolfboot_build_profile_config(config)


def test_validate_wolfboot_build_profile_accepts_phase_11_5d_expanded_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_stm32l4_rsa4096",
        "description": "RSA4096 build profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "rsa4096",
        "boot_profile": "wolfboot_rsa4096",
        "build": {
            "command": "make",
            "config_template": "testdata/wolfboot/stm32l4r5_rsa4096.config",
            "generated_config": "tools/wolfboot/.config",
        },
    }

    experiment_cli.validate_wolfboot_build_profile_config(config)


def test_validate_wolfboot_build_profile_accepts_mldsa_header_fit_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_stm32l4_mldsa65",
        "description": "ML-DSA-65 build profile.",
        "source_dir": "tools/wolfboot",
        "output_dir": "tools/wolfboot",
        "artifact": "tools/wolfboot/wolfboot.elf",
        "target": "stm32l4r5_project_local",
        "signature_algorithm": "mldsa65",
        "boot_profile": "wolfboot_mldsa65",
        "build": {
            "command": "make",
            "config_template": "testdata/wolfboot/stm32l4r5_mldsa65.config",
            "generated_config": "tools/wolfboot/.config",
        },
    }

    experiment_cli.validate_wolfboot_build_profile_config(config)


def test_validate_application_signing_profile_accepts_mldsa_header_fit_algorithm():
    experiment_cli = load_experiment_module()

    config = {
        "id": "wolfboot_mldsa65_app",
        "description": "ML-DSA-65 signing profile.",
        "input_image": "build/Release/stm32_basic_hal1_mldsa65.bin",
        "signed_image": "build/Release/stm32_basic_hal1_mldsa65_v1_signed.bin",
        "signature_algorithm": "mldsa65",
        "private_key": "secrets/wolfboot/mldsa65_private_key.der",
        "image_version": 1,
        "sign": {
            "command": "tools/keytools/sign",
            "args": "--ml_dsa {input_image} {private_key} {image_version}",
        },
    }

    experiment_cli.validate_application_signing_profile_config(config)


def minimal_mqtt_experiment_config() -> dict[str, object]:
    return {
        "id": "mqtt_tls_schema_fake",
        "description": "Phase M2 MQTT/TLS schema-only experiment.",
        "board": "board_a",
        "host": "gateway",
        "boot": "direct_flash",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Release/stm32_basic_hal1.elf",
        },
        "uart": {
            "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
            "expected_tick_message": "tick",
        },
        "mqtt": {
            "schema_version": 1,
            "evidence_class": "fake_no_network",
            "transport_backend": "fake_no_network",
            "tls": {
                "mode": "not_applicable",
            },
            "result_schema": {
                "unavailable_metrics": {
                    "wifi_association": "Fake/no-network transport does not use Wi-Fi hardware.",
                    "ip_address": "Fake/no-network transport does not acquire an IP address.",
                    "tcp_connect": "Fake/no-network transport does not open a TCP socket.",
                    "tls_handshake": "Phase M2 does not perform a TLS handshake.",
                    "mqtt_connect": "Phase M2 does not connect to an MQTT broker.",
                    "mqtt_publish": "Phase M2 does not publish MQTT messages.",
                    "mqtt_reconnect": "Phase M2 does not exercise reconnect behaviour.",
                    "latency_ms": "Phase M2 has no runtime latency evidence.",
                    "throughput_bytes_per_second": "Phase M2 has no throughput evidence.",
                }
            },
        },
    }


def test_validate_mqtt_tls_config_accepts_fake_no_network_schema_only_config():
    experiment_cli = load_experiment_module()

    experiment_cli.validate_experiment_config(minimal_mqtt_experiment_config())


def test_validate_mqtt_tls_config_accepts_host_side_schema_with_broker_reference():
    experiment_cli = load_experiment_module()
    config = minimal_mqtt_experiment_config()
    config["mqtt"]["evidence_class"] = "host_side"
    config["mqtt"]["transport_backend"] = "host_socket"
    config["mqtt"]["tls"] = {
        "mode": "classical_tls",
        "key_exchange_group": "secp256r1",
        "certificate_profile": "server-ecdsa-p256",
        "certificate_authority_algorithm": "ecdsa-p256",
        "server_certificate_algorithm": "ecdsa-p256",
    }
    config["mqtt"]["broker"] = {
        "host": "pqc-gateway1",
        "port": 8883,
        "dns_required": True,
    }

    experiment_cli.validate_experiment_config(config)


def test_validate_mqtt_tls_config_rejects_backend_evidence_mismatch():
    experiment_cli = load_experiment_module()
    config = minimal_mqtt_experiment_config()
    config["mqtt"]["transport_backend"] = "host_socket"

    with pytest.raises(experiment_cli.ConfigError, match="not compatible"):
        experiment_cli.validate_experiment_config(config)


def test_validate_mqtt_tls_config_rejects_missing_unavailable_runtime_metrics_for_build_only():
    experiment_cli = load_experiment_module()
    config = minimal_mqtt_experiment_config()
    config["mqtt"]["evidence_class"] = "stm32_build_only"
    config["mqtt"]["transport_backend"] = "stm32_build_only"
    del config["mqtt"]["result_schema"]["unavailable_metrics"]["mqtt_publish"]

    with pytest.raises(experiment_cli.ConfigError, match="runtime metrics unavailable"):
        experiment_cli.validate_experiment_config(config)


def test_validate_mqtt_tls_config_rejects_private_key_references():
    experiment_cli = load_experiment_module()
    config = minimal_mqtt_experiment_config()
    config["mqtt"]["evidence_class"] = "host_side"
    config["mqtt"]["transport_backend"] = "host_socket"
    config["mqtt"]["broker"] = {
        "host": "pqc-gateway1",
        "port": 8883,
    }
    config["mqtt"]["tls"] = {
        "mode": "classical_tls",
        "certificate_refs": {
            "client_private_key": "secrets/mqtt/client.key",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="must not be declared"):
        experiment_cli.validate_experiment_config(config)


def test_validate_mqtt_tls_config_accepts_fake_transport_harness_fields():
    experiment_cli = load_experiment_module()
    config = minimal_mqtt_experiment_config()
    config["mqtt"]["fake_transport"] = {
        "scenario": "publish_timeout_then_disconnect",
        "connect_outcome": "success",
        "publish_outcome": "timeout",
        "disconnect_outcome": "success",
        "reconnect_outcome": "success",
        "reconnect_attempts": 1,
        "topic": "pqc/fake/no-network",
        "message": "fake payload",
    }

    experiment_cli.validate_experiment_config(config)


def test_validate_mqtt_tls_config_rejects_invalid_fake_transport_outcome():
    experiment_cli = load_experiment_module()
    config = minimal_mqtt_experiment_config()
    config["mqtt"]["fake_transport"] = {
        "connect_outcome": "real_socket_connect",
    }

    with pytest.raises(experiment_cli.ConfigError, match="connect_outcome"):
        experiment_cli.validate_experiment_config(config)


def test_validate_mqtt_tls_config_rejects_fake_transport_with_non_fake_backend():
    experiment_cli = load_experiment_module()
    config = minimal_mqtt_experiment_config()
    config["mqtt"]["evidence_class"] = "host_side"
    config["mqtt"]["transport_backend"] = "host_socket"
    config["mqtt"]["broker"] = {
        "host": "pqc-gateway1",
        "port": 8883,
        "dns_required": True,
    }
    config["mqtt"]["tls"] = {
        "mode": "classical_tls",
        "key_exchange_group": "secp256r1",
        "certificate_profile": "server-ecdsa-p256",
        "certificate_authority_algorithm": "ecdsa-p256",
        "server_certificate_algorithm": "ecdsa-p256",
    }
    config["mqtt"]["fake_transport"] = {
        "connect_outcome": "success",
    }

    with pytest.raises(experiment_cli.ConfigError, match="fake_transport requires"):
        experiment_cli.validate_experiment_config(config)


def test_validate_experiment_network_requires_valid_wifi_and_dhcp():
    experiment_cli = load_experiment_module()
    config = {
        "id": "baseline_direct_uart",
        "description": "Wi-Fi DHCP experiment.",
        "board": "board_a",
        "host": "gateway",
        "boot": "direct_flash",
        "firmware": {"mode": "direct_flash", "artifact": "build/Release/stm32_basic_hal1.elf"},
        "uart": {"expected_boot_message": "boot", "expected_tick_message": "tick"},
        "network": {
            "wifi": {"ssid": "hiphopopotamus", "psk": "lukeisadog"},
            "ipv4": {"mode": "dhcp"},
        },
    }
    experiment_cli.validate_experiment_config(config)
    config["network"]["wifi"]["psk"] = "short"
    with pytest.raises(experiment_cli.ConfigError, match="between 8 and 63 bytes"):
        experiment_cli.validate_experiment_config(config)


def _minimal_mqtt_dns_config(host: str, dns_required):
    return {
        "mqtt": {
            "schema_version": 1,
            "evidence_class": "stm32_st67_classical_tls_e2e",
            "transport_backend": "st67w61m1_lwip_wolfssl",
            "broker": {"host": host, "port": 8883, "dns_required": dns_required},
            "tls": {
                "mode": "classical_tls_server_auth",
                "key_exchange_group": "secp256r1",
                "certificate_profile": "server-ecdsa-p256",
                "certificate_authority_algorithm": "ecdsa-p256",
                "server_certificate_algorithm": "ecdsa-p256",
            },
            "result_schema": {"unavailable_metrics": {}},
        }
    }


def test_mqtt_hostname_requires_dns_required_true():
    experiment_cli = load_experiment_module()
    with pytest.raises(experiment_cli.ConfigError, match="dns_required must be true"):
        experiment_cli.validate_mqtt_tls_config(
            _minimal_mqtt_dns_config("pqc-gateway1.pqcnet", False)
        )


def test_mqtt_ip_literal_allows_dns_not_required():
    experiment_cli = load_experiment_module()
    experiment_cli.validate_mqtt_tls_config(
        _minimal_mqtt_dns_config("10.1.1.18", False)
    )


def test_mqtt_dns_required_must_be_boolean():
    experiment_cli = load_experiment_module()
    with pytest.raises(experiment_cli.ConfigError, match="dns_required must be a boolean"):
        experiment_cli.validate_mqtt_tls_config(
            _minimal_mqtt_dns_config("pqc-gateway1.pqcnet", "true")
        )


def test_validate_experiment_config_defaults_mqtt_validation_application():
    experiment_cli = load_experiment_module()
    config = {
        "id": "baseline_direct_uart", "description": "Default application.",
        "board": "board_a", "host": "gateway", "boot": "direct_flash",
        "firmware": {"mode": "direct_flash", "artifact": "build/Release/stm32_basic_hal1.elf"},
        "uart": {"expected_boot_message": "boot", "expected_tick_message": "tick"},
    }
    experiment_cli.validate_experiment_config(config)
    assert config["firmware"]["application"] == "mqtt_validation"


def test_validate_experiment_config_rejects_unknown_firmware_application():
    experiment_cli = load_experiment_module()
    config = {
        "id": "baseline_direct_uart", "description": "Unknown application.",
        "board": "board_a", "host": "gateway", "boot": "direct_flash",
        "firmware": {"application": "unknown", "mode": "direct_flash", "artifact": "build/Release/stm32_basic_hal1.elf"},
        "uart": {"expected_boot_message": "boot", "expected_tick_message": "tick"},
    }
    with pytest.raises(experiment_cli.ConfigError, match="firmware.application"):
        experiment_cli.validate_experiment_config(config)


def test_validate_experiment_config_defaults_uart_log_level_to_info():
    experiment_cli = load_experiment_module()
    config = {
        "id": "baseline_direct_uart", "description": "Default UART level.",
        "board": "board_a", "host": "gateway", "boot": "direct_flash",
        "firmware": {"mode": "direct_flash", "artifact": "build/Release/stm32_basic_hal1.elf"},
        "uart": {"expected_boot_message": "boot", "expected_tick_message": "[tick="},
    }
    experiment_cli.validate_experiment_config(config)
    assert config["firmware"]["uart_log_level"] == "info"


def test_validate_experiment_config_rejects_unknown_uart_log_level():
    experiment_cli = load_experiment_module()
    config = {
        "id": "baseline_direct_uart", "description": "Unknown UART level.",
        "board": "board_a", "host": "gateway", "boot": "direct_flash",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Release/stm32_basic_hal1.elf",
            "uart_log_level": "verbose",
        },
        "uart": {"expected_boot_message": "boot", "expected_tick_message": "[tick="},
    }
    with pytest.raises(experiment_cli.ConfigError, match="firmware.uart_log_level"):
        experiment_cli.validate_experiment_config(config)


def test_validate_experiment_config_accepts_tick_prefix_instead_of_heartbeat():
    experiment_cli = load_experiment_module()
    config = {
        "id": "mqtt_plaintext_st67_e2e",
        "description": "Structured UART tick prefix.",
        "board": "board_a",
        "host": "gateway",
        "boot": "direct_flash",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Release/stm32_basic_hal1.elf",
        },
        "uart": {
            "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
            "expected_tick_prefix": "[tick=",
        },
    }

    experiment_cli.validate_experiment_config(config)


def test_validate_experiment_config_requires_tick_message_or_prefix():
    experiment_cli = load_experiment_module()
    config = {
        "id": "mqtt_plaintext_st67_e2e",
        "description": "Missing UART timing evidence.",
        "board": "board_a",
        "host": "gateway",
        "boot": "direct_flash",
        "firmware": {
            "mode": "direct_flash",
            "artifact": "build/Release/stm32_basic_hal1.elf",
        },
        "uart": {
            "expected_boot_message": "stm32-basic_hal1 boot v0.1.0",
        },
    }

    with pytest.raises(experiment_cli.ConfigError, match="expected_tick_message or"):
        experiment_cli.validate_experiment_config(config)


def test_load_experiment_bundle_rejects_non_generated_operational_input(tmp_path):
    experiment_cli = load_experiment_module()
    source_profile = tmp_path / "source.yaml"
    source_profile.write_text("id: unsupported\n", encoding="utf-8")
    with pytest.raises(experiment_cli.ConfigError, match="resolver-generated cases"):
        experiment_cli.load_experiment_bundle(source_profile)
