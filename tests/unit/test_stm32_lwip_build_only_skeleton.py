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
    assert "PQC_LwIP_BuildOnly_RuntimeSmokeLine" in header
    assert "lwIP runtime smoke:" in source
    assert "ip4_format=%s" in source
    assert "IP4_ADDR(&example_addr, 192, 0, 2, 1)" in source
    assert "network=unavailable" in source
    assert "TLS" in source
    assert "MQTT" in source


def test_stm32_lwip_build_only_skeleton_does_not_start_runtime_networking():
    source = Path("Core/Src/pqc_lwip_build_only.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")
    freertos_c = Path("Core/Src/freertos.c").read_text(encoding="utf-8")

    forbidden_fragments = (
        "MX_LWIP_Init",
        "netif_add",
        "dhcp_start",
        "MQTTConnect",
        "wolfSSL_connect",
    )

    for fragment in forbidden_fragments:
        assert fragment not in source

    assert "PQC_LwIP_BuildOnly_Init" in main_c
    assert "PQC_LwIP_BuildOnly_RuntimeSmokeLine" in main_c
    assert "lwIP runtime smoke:" in main_c
    assert "PQC_LwIP_BuildOnly_Init" not in freertos_c


def test_stm32_lwip_runtime_smoke_is_limited_to_non_network_helpers():
    source = Path("Core/Src/pqc_lwip_build_only.c").read_text(encoding="utf-8")

    required_fragments = (
        "lwip/init.h",
        "lwip/ip4_addr.h",
        "lwip/inet_chksum.h",
        "LWIP_VERSION_MAJOR",
        "IP4_ADDR(&example_addr, 192, 0, 2, 1)",
        "ip4addr_ntoa_r",
        "inet_chksum",
        "network=unavailable",
    )

    for fragment in required_fragments:
        assert fragment in source

    forbidden_fragments = (
        "lwip_init(",
        "netif_add(",
        "netif_set_up(",
        "dhcp_start(",
        "tcp_connect(",
        "mqtt_client_connect(",
        "W6X_Init(",
        "W6X_WiFi_Connect(",
    )

    for fragment in forbidden_fragments:
        assert fragment not in source


def test_phase_m6_2_network_interface_boundary_uses_lwip_netif_state():
    root_cmake = Path("CMakeLists.txt").read_text(encoding="utf-8")
    header = Path("Core/Inc/pqc_network_interface.h").read_text(encoding="utf-8")
    source = Path("Core/Src/pqc_network_interface.c").read_text(encoding="utf-8")
    main_c = Path("Core/Src/main.c").read_text(encoding="utf-8")

    assert "Core/Src/pqc_network_interface.c" in root_cmake
    assert "PQC_NetworkInterfaceStatus" in header
    assert "lwip_netif_up" in header
    assert "lwip_link_up" in header
    assert "lwip_ipv4_any" in header
    assert "struct netif s_pqc_unavailable_netif" in source
    assert "netif_is_up(&s_pqc_unavailable_netif)" in source
    assert "netif_is_link_up(&s_pqc_unavailable_netif)" in source
    assert "ip4_addr_isany_val(*netif_ip4_addr(&s_pqc_unavailable_netif))" in source
    assert "ip4addr_ntoa_r(" in source
    assert "availability_from_bool(link_up)" in source
    assert "availability_from_bool(ip_available)" in source
    assert "availability_from_bool(tcp_ready)" in source
    assert "evidence=lwip-netif-state-only" in source
    assert "lwip_netif_up=%u" in source
    assert "lwip_link_up=%u" in source
    assert "lwip_ipv4_any=%u" in source
    assert "lwip_ipv4=%s" in source
    assert "PQC_NetworkInterface_Init" in main_c
    assert "PQC_NetworkInterface_StatusLine" in main_c
    assert "APP_PrintNetworkInterfaceStatus();" in main_c


def test_phase_m6_2_network_interface_boundary_maps_unconfigured_lwip_state_to_unavailable():
    source = Path("Core/Src/pqc_network_interface.c").read_text(encoding="utf-8")

    assert "memset(&s_pqc_unavailable_netif, 0" in source
    assert "netif_set_addr(" not in source
    assert "sys_now(" not in source
    assert "const bool ip_available = netif_up && !ipv4_any;" in source
    assert "const bool tcp_ready = netif_up && link_up && ip_available;" in source
    assert 'return "unavailable";' in source
    assert "link=%s" in source
    assert "ip=%s" in source
    assert "tcp=%s" in source
    assert "transport=%s" in source


def test_phase_m6_2_network_interface_boundary_does_not_bring_up_networking():
    source = Path("Core/Src/pqc_network_interface.c").read_text(encoding="utf-8")

    forbidden_fragments = (
        "netif_add(",
        "netif_set_up(",
        "netif_set_link_up(",
        "dhcp_start(",
        "tcp_new(",
        "tcp_connect(",
        "wolfSSL_connect(",
        "MQTTConnect(",
        "W6X_Init(",
        "W6X_WiFi_Connect(",
    )

    for fragment in forbidden_fragments:
        assert fragment not in source

    required_unavailable_fields = (
        "wifi_module=unavailable",
        "st67w61m1=unavailable",
        "tls_handshake=unavailable",
        "mqtt_connect=unavailable",
        "mqtt_publish=unavailable",
        "reconnect=unavailable",
        "end_to_end=unavailable",
    )

    for fragment in required_unavailable_fields:
        assert fragment in source
