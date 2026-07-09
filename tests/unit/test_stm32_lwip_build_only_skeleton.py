from pathlib import Path


def test_stm32_lwip_build_only_skeleton_is_compiled_into_firmware():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")

    assert "Core/Src/pqc_lwip_build_only.c" in root_cmake
    assert "Core/Inc" in root_cmake


def test_stm32_lwip_build_only_boundary_declares_unavailable_runtime_networking():
    header = Path("Core/Inc/pqc_lwip_build_only.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_lwip_build_only.c").read_text(encoding="utf-8")

    assert "PQC_LwIPBuildOnlyStatus" in header
    assert ".lwip_build_boundary_present = true" in source
    assert ".network_interface_available = false" in source
    assert ".wifi_module_required = false" in source
    assert ".ip_address_available = false" in source
    assert ".tcp_transport_available = false" in source
    assert "STM32 lwIP build-only skeleton evidence" in source
    assert "TLS" in source
    assert "MQTT" in source


def test_stm32_lwip_build_only_skeleton_does_not_pull_runtime_lwip_or_wifi_stack():
    source = Path("Core/Src/pqc_lwip_build_only.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    freertos_c = Path("Core/Src/freertos.c").read_text(encoding="utf-8")

    forbidden_fragments = (
        "#include <lwip/",
        "#include \"lwip/",
        "MX_LWIP_Init",
        "netif_add",
        "dhcp_start",
        "MQTTConnect",
        "wolfSSL_connect",
    )

    for fragment in forbidden_fragments:
        assert fragment not in source

    assert "PQC_LwIP_BuildOnly_Init" not in main_c
    assert "PQC_LwIP_BuildOnly_Init" not in freertos_c
