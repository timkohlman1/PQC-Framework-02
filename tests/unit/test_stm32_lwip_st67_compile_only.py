from __future__ import annotations

from pathlib import Path


def _read(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding="utf-8")


def test_lwip_and_st67_sources_are_wired_into_generated_cmake() -> None:
    cmake = _read("cmake/stm32cubemx/CMakeLists.txt")

    required_fragments = (
        "set(LwIP_Src",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/init.c",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/pbuf.c",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/tcp.c",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/udp.c",
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c",
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/w61_io.c",
        "Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_netif.c",
        "Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_wifi.c",
        "ST67W6X/Target/spi_port.c",
        "list(FILTER MX_Application_Src EXCLUDE REGEX",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/system/OS/sys_arch.c",
        "Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2/cmsis_os2.c",
        "set_source_files_properties(",
        "PROPERTIES COMPILE_OPTIONS \"-include;stdint.h;-include;cmsis_gcc.h\"",
    )

    for fragment in required_fragments:
        assert fragment in cmake

    excluded_runtime_fragments = (
        "/LWIP/App/(altls_mbedtls|sntp|dhcp_server_raw|http_client|lwip|lwip_netif)",
        "/Utils/Performance/",
        "/Core/w6x_(ble|http|mqtt)",
    )

    for fragment in excluded_runtime_fragments:
        assert fragment in cmake


def test_lwip_and_st67_source_tree_contains_expected_compile_only_inputs() -> None:
    required_paths = (
        "LWIP/App/lwip.c",
        "LWIP/App/lwip.h",
        "LWIP/App/lwip_netif.c",
        "LWIP/Target/lwipopts.h",
        "LWIP/Target/arch/cc.h",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/lwip/init.h",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/lwip/pbuf.h",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/init.c",
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/pbuf.c",
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c",
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/w61_io.c",
        "ST67W6X/Target/spi_port.c",
    )

    for relative_path in required_paths:
        assert Path(relative_path).is_file(), relative_path


def test_lwip_options_use_cmsis_rtos_v2_os_port_without_runtime_startup() -> None:
    lwipopts = _read("LWIP/Target/lwipopts.h")
    sys_arch_h = _read("LWIP/Target/arch/sys_arch.h")
    cmake = _read("cmake/stm32cubemx/CMakeLists.txt")

    assert "#define LWIP_NETIF_API                1" in lwipopts
    assert "#define LWIP_DHCP                     1" in lwipopts
    assert "#define NO_SYS                       1" not in lwipopts
    assert "#define LWIP_NETCONN                 0" not in lwipopts
    assert "#define LWIP_SOCKET                  0" not in lwipopts

    assert '#include "cmsis_os2.h"' in sys_arch_h
    assert "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/system/OS/sys_arch.c" in cmake
    assert "Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2/cmsis_os2.c" in cmake
    assert "list(FILTER LwIP_Src EXCLUDE REGEX" not in cmake


def test_st67_spi_gpio_clock_and_interrupt_configuration_is_static_only() -> None:
    main_h = _read("Core/Inc/main.h")
    main_c = _read("Core/Src/main.c")
    it_c = _read("Core/Src/stm32l4xx_it.c")
    freertos_config = _read("Core/Inc/FreeRTOSConfig.h")

    pin_fragments = (
        "#define SPI_SCK_Pin GPIO_PIN_5",
        "#define SPI_SCK_GPIO_Port GPIOA",
        "#define SPI_MISO_Pin GPIO_PIN_6",
        "#define SPI_MISO_GPIO_Port GPIOA",
        "#define SPI_MOSI_Pin GPIO_PIN_7",
        "#define SPI_MOSI_GPIO_Port GPIOA",
        "#define SPI_CS_Pin GPIO_PIN_14",
        "#define SPI_CS_GPIO_Port GPIOD",
        "#define CHIP_EN_Pin GPIO_PIN_11",
        "#define CHIP_EN_GPIO_Port GPIOE",
        "#define BOOT_Pin GPIO_PIN_9",
        "#define BOOT_GPIO_Port GPIOE",
        "#define SPI_RDY_Pin GPIO_PIN_13",
        "#define SPI_RDY_GPIO_Port GPIOE",
        "#define USER_BUTTON_Pin GPIO_PIN_15",
        "#define USER_BUTTON_GPIO_Port GPIOF",
    )

    for fragment in pin_fragments:
        assert fragment in main_h

    assert "PWR_REGULATOR_VOLTAGE_SCALE1_BOOST" in main_c
    assert "RCC_PLLSOURCE_HSI" in main_c
    assert "RCC_OscInitStruct.PLL.PLLN = 15" in main_c
    assert "RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK" in main_c
    assert "FLASH_LATENCY_5" in main_c
    assert "hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_4" in main_c
    assert "#define configTOTAL_HEAP_SIZE                    ((size_t)40000)" in freertos_config

    assert "HAL_GPIO_EXTI_IRQHandler(SPI_RDY_Pin);" in it_c
    assert "HAL_GPIO_EXTI_IRQHandler(USER_BUTTON_Pin);" in it_c
    assert "HAL_GPIO_EXTI_IRQHandler(USER_BUTTON_GPIO_Pin);" not in it_c


def test_lwip_st67_preparation_does_not_claim_runtime_network_success() -> None:
    main_c = _read("Core/Src/main.c")
    freertos_c = _read("Core/Src/freertos.c")
    architecture = _read("docs/007_framework_architecture.md")
    readme = _read("README.md")

    runtime_entrypoints = (
        "MX_LWIP_Init()",
        "MX_LWIP_Init();",
        "W6X_Init(",
        "W6X_WiFi_Connect(",
        "dhcp_start(",
        "mqtt_client_connect(",
        "MQTTConnect(",
        "wolfSSL_connect(",
    )

    for source in (main_c, freertos_c):
        for fragment in runtime_entrypoints:
            assert fragment not in source

    assert 'APP_PrintLwIPRuntimeSmoke("pre_scheduler", false);' in main_c
    assert 'APP_PrintLwIPRuntimeSmoke("freertos_task", true);' in main_c
    assert "lwIP runtime smoke:" in main_c
    assert "network=unavailable" in main_c
    assert "PQC_LwIP_BuildOnly_RuntimeSmokeLine" not in freertos_c

    for doc in (architecture, readme):
        assert "compile/link evidence only" in doc
        assert "does not initialize" in doc or "does not claim" in doc
        assert "Wi-Fi association" in doc
        assert "MQTT connect" in doc
        assert "end-to-end wireless success" in doc


def test_lwip_runtime_smoke_marker_is_non_network_uart_evidence_only() -> None:
    header = _read("Core/Inc/pqc_lwip_build_only.h")
    source = _read("Core/Src/pqc_lwip_build_only.c")
    main_c = _read("Core/Src/main.c")
    architecture = _read("docs/007_framework_architecture.md")
    readme = _read("README.md")

    assert "PQC_LwIP_BuildOnly_RuntimeSmokeLine" in header
    assert "LWIP_VERSION_MAJOR" in source
    assert "ip4addr_ntoa_r" in source
    assert "inet_chksum" in source
    assert "lwIP runtime smoke: context=%s scheduler=%s version=" in source
    assert "ip4_format=%s" in source
    assert "IP4_ADDR(&example_addr, 192, 0, 2, 1)" in source
    assert "network=unavailable" in source
    assert 'APP_PrintLwIPRuntimeSmoke("pre_scheduler", false);' in main_c
    assert 'APP_PrintLwIPRuntimeSmoke("freertos_task", true);' in main_c
    assert 'scheduler_running ? "running" : "not_started"' in source

    forbidden_runtime_network_fragments = (
        "lwip_init(",
        "MX_LWIP_Init(",
        "netif_add(",
        "netif_set_up(",
        "dhcp_start(",
        "tcp_connect(",
        "mqtt_client_connect(",
        "W6X_Init(",
        "W6X_WiFi_Connect(",
    )

    for fragment in forbidden_runtime_network_fragments:
        assert fragment not in source
        assert fragment not in main_c

    for doc in (architecture, readme):
        assert "non-network lwIP runtime smoke" in doc
        assert "version, IPv4 formatting, and checksum helpers" in doc
        assert "does not initialize a netif" in doc
