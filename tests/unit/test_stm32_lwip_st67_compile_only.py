from __future__ import annotations

from pathlib import Path


def _read(relative_path: str) -> str:
    return Path(relative_path).read_text(encoding="utf-8")


def _function_definition(source: str, signature: str, next_signature: str) -> str:
    """Return a C function definition, skipping any earlier prototype."""

    definition_start = source.index(f"{signature}\n{{")
    definition_end = source.index(next_signature, definition_start + len(signature))
    return source[definition_start:definition_end]


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
        "/LWIP/App/(altls_mbedtls|sntp|dhcp_server_raw|http_client)",
        "/Utils/Performance/",
        "/Core/w6x_(ble|http|mqtt)",
    )

    for fragment in excluded_runtime_fragments:
        assert fragment in cmake

    assert "LWIP/App/lwip.c" in cmake
    assert "LWIP/App/lwip_netif.c" in cmake
    assert "|lwip|lwip_netif)" not in cmake


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
    assert "#define LWIP_IPV6                     0" in lwipopts
    assert "#define LWIP_IPV6_DHCP6               0" in lwipopts
    assert "#define LWIP_IPV6_MLD                 0" in lwipopts
    assert "#define LWIP_IPV6_ND                  0" in lwipopts
    assert "#define LWIP_IPV6_FORWARD             0" in lwipopts
    assert "#define LWIP_IPV6_ROUTE_TABLE_SUPPORT 0" in lwipopts
    assert "MEMP_NUM_MLD6_GROUP" not in lwipopts
    assert "IPV6_FRAG_COPYHEADER" not in lwipopts
    assert "/src/core/ipv6/" not in cmake
    assert "#define PPP_SUPPORT                   0" in lwipopts
    assert "#define PPPOE_SUPPORT                 0" in lwipopts
    assert "#define PPPOS_SUPPORT                 0" in lwipopts
    assert "#define PPPOL2TP_SUPPORT              0" in lwipopts
    assert "/src/netif/ppp/" not in cmake
    assert "/src/include/netif/ppp/" not in cmake
    assert "/src/netif/bridgeif.c" not in cmake
    assert "/src/netif/bridgeif_fdb.c" not in cmake
    assert "/src/netif/slipif.c" not in cmake
    assert "/src/netif/ethernet.c" in cmake
    assert "#define NO_SYS                       1" not in lwipopts
    assert "#define LWIP_NETCONN                 0" not in lwipopts
    assert "#define LWIP_SOCKET                  0" not in lwipopts

    assert '#include "cmsis_os2.h"' in sys_arch_h
    assert "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/system/OS/sys_arch.c" in cmake
    assert "Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2/cmsis_os2.c" in cmake
    assert "list(FILTER LwIP_Src EXCLUDE REGEX" not in cmake


def test_st67_spi_gpio_clock_interrupt_and_runtime_bringup_are_wired() -> None:
    main_h = _read("Core/Inc/main.h")
    main_c = _read("Core/Src/main.c")
    application = _read("Core/Src/pqc_mqtt_application_mqtt_validation.c")
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
    ioc = _read("stm32_basic_hal1.ioc")
    assert "SPI1.BaudRatePrescaler=SPI_BAUDRATEPRESCALER_4" in ioc
    assert "SPI1.CalculateBaudRate=3.75 MBits/s" in ioc
    assert "#define configTOTAL_HEAP_SIZE                    ((size_t)40000)" in freertos_config

    assert "HAL_GPIO_EXTI_IRQHandler(SPI_RDY_Pin);" in it_c
    assert "HAL_GPIO_EXTI_IRQHandler(USER_BUTTON_Pin);" in it_c
    assert "HAL_GPIO_EXTI_IRQHandler(USER_BUTTON_GPIO_Pin);" not in it_c

    assert '#include "w6x_api.h"' in main_c
    assert '#include "spi_iface.h"' in main_c
    assert '#include "logging.h"' in main_c
    assert "static void APP_RunST67SPIBringup(void)" in main_c
    assert "vLoggingInit(APP_UART_WriteString)" in main_c
    assert "status = W6X_RegisterAppCb(&app_st67_callbacks);" in main_c
    assert "status = W6X_Init();" in main_c
    assert "status = W6X_WiFi_Init();" in main_c
    assert "status = W6X_WiFi_Connect(&options);" in main_c
    assert ".run_network_bringup = APP_RunST67SPIBringup" in main_c
    assert "PQC_MQTT_ApplicationRun(&fixture);" in main_c
    assert "fixture->run_network_bringup();" in application
    assert "if (!fixture->is_network_ready())" in application
    assert "void StartNetworkTask(void *argument)" in main_c
    assert "networkTaskHandle = osThreadNew(StartNetworkTask" in main_c
    assert "PQC_WIFI_SSID[0] == '\\0'" in main_c
    assert "result=config_missing ssid=<empty>" in main_c
    assert "ST67 SPI bring-up: delayed 3000 ms for logic analyser capture" not in main_c
    assert "osDelay(3000U);" not in main_c
    assert "void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)" in main_c
    assert "if (GPIO_Pin == SPI_RDY_Pin)" in main_c
    assert (
        "GPIO_PinState ready_level = "
        "HAL_GPIO_ReadPin(SPI_RDY_GPIO_Port, SPI_RDY_Pin);"
        in main_c
    )
    assert "if (ready_level == GPIO_PIN_SET)" in main_c
    assert "(void)spi_on_txn_data_ready();" in main_c
    assert "(void)spi_on_header_ack();" in main_c
    assert "APP_ST67ReadyDiagnosticSnapshot" in main_h
    assert "APP_ST67ReadyDiagnosticSnapshotGet" in main_h
    assert "static volatile APP_ST67ReadyDiagnosticSnapshot app_st67_ready_diagnostic;" in main_c
    assert "xTaskGetTickCountFromISR()" in main_c
    assert "HAL_NVIC_DisableIRQ(EXTI15_10_IRQn);" in main_c
    assert "static void APP_EnableST67EXTIInterrupt(void)" in main_c
    assert "__HAL_GPIO_EXTI_CLEAR_IT(SPI_RDY_Pin);" in main_c
    assert "__HAL_GPIO_EXTI_CLEAR_IT(USER_BUTTON_Pin);" in main_c
    assert "HAL_NVIC_ClearPendingIRQ(EXTI15_10_IRQn);" in main_c
    assert "HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);" in main_c
    assert "xTaskGetSchedulerState() == taskSCHEDULER_NOT_STARTED" in main_c
    gpio_init_start = main_c.index("static void MX_GPIO_Init(void)\n{")
    gpio_init_end = main_c.index("/* USER CODE BEGIN 4 */", gpio_init_start)
    gpio_init_body = main_c[gpio_init_start:gpio_init_end]
    assert "HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);" not in gpio_init_body
    bringup_start = main_c.index("static void APP_RunST67SPIBringup(void)\n{")
    bringup_end = main_c.index("static void APP_PrintLwIPRuntimeSmoke", bringup_start)
    bringup_body = main_c[bringup_start:bringup_end]
    assert bringup_body.index("APP_EnableST67EXTIInterrupt();") < bringup_body.index("status = W6X_Init();")
    spi_port_c = _read("ST67W6X/Target/spi_port.c")
    assert "static uint32_t spi_port_tick_from_isr(void)" in spi_port_c
    assert "return HAL_GetTick();" in spi_port_c
    assert "spi_port_diag.completed_tick = spi_port_tick_from_isr();" in spi_port_c
    assert "app_st67_ready_diagnostic.irq_count++;" in main_c
    assert "app_st67_ready_diagnostic.rising_count++;" in main_c
    assert "app_st67_ready_diagnostic.falling_count++;" in main_c
    network_task_definition = main_c.rindex("void StartNetworkTask(void *argument)")
    network_task_body = main_c[network_task_definition:]
    assert "PQC_MQTT_ApplicationRun(&fixture);" in network_task_body
    assert "APP_RunST67SPIBringup();" not in network_task_body
    default_task_definition = main_c.rindex("void StartDefaultTask(void *argument)")
    default_task_body = main_c[default_task_definition:network_task_definition]
    assert "APP_RunST67SPIBringup();" not in default_task_body
    assert 'APP_UART_WriteString("FreeRTOS defaultTask started\\r\\n");' in default_task_body
    assert "HAL_GPIO_TogglePin(GPIOB, GPIO_PIN_7);" in default_task_body
    assert "osDelay(1000);" in default_task_body
    assert "evidence=stm32-st67-gpio-spi-bringup-only" in main_c
    assert "wifi_association=not-attempted" in main_c
    assert "end_to_end=unavailable" in main_c


def test_st67_wifi_join_and_dhcp_emit_redacted_machine_readable_evidence() -> None:
    main_c = _read("Core/Src/main.c")
    required = (
        '#include "pqc_wifi_config.h"',
        "MX_LWIP_Init()",
        "W6X_WiFi_Connect(&options)",
        "W6X_WiFi_Station_GetState",
        "netif_get_interface(NETIF_STA)",
        "ST67 Wi-Fi association: result=passed",
        "ST67 DHCP: result=",
        "psk=redacted",
        "W6X_WiFi_Scan(&options, APP_ST67WiFiScanCallback)",
        "ST67 Wi-Fi scan: begin",
        "ST67 Wi-Fi scan result: index=",
        "rssi_dbm=",
        "security=",
        "ST67 Wi-Fi scan summary: result=",
        "configured_ssid_found=",
    )
    for fragment in required:
        assert fragment in main_c
    assert "PQC_WIFI_PSK" in main_c
    assert "W6X_Net_Station_GetIPAddress" not in main_c
    assert "lukeisadog" not in main_c
    assert "APP_ST67_WIFI_SCAN_MAX_RESULTS  10U" in main_c
    assert "APP_ST67_WIFI_SCAN_TIMEOUT_MS 8000U" in main_c
    assert "APP_RunST67WiFiScan();" in main_c


def test_lwip_st67_runtime_claims_are_bounded_to_association_and_dhcp() -> None:
    main_c = _read("Core/Src/main.c")
    assert "W6X_WiFi_Connect(&options)" in main_c
    assert "APP_WaitForDhcpAddress" in main_c
    assert "wolfSSL_connect(" not in main_c
    assert "MQTTConnect(" not in main_c
    assert "mqtt_client_connect(" not in main_c
    assert "tls_handshake=unavailable" in main_c
    assert "mqtt_connect=unavailable" in main_c
    assert "end_to_end=unavailable" in main_c


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
        "W6X_WiFi_Connect(",
    )

    for fragment in forbidden_runtime_network_fragments:
        assert fragment not in source

    for doc in (architecture, readme):
        assert "non-network lwIP runtime smoke" in doc
        assert "version, IPv4 formatting, and checksum helpers" in doc
        assert "does not initialize a netif" in doc


def test_st67_wifi_dhcp_runtime_configuration():
    main_c = _read("Core/Src/main.c")
    assert "W6X_WiFi_Connect(&options)" in main_c
    assert "APP_WaitForDhcpAddress" in main_c
    assert "ST67 DHCP: result=" in main_c
    assert "psk=redacted" in main_c


def test_lwip_runtime_source_does_not_require_demo_app_config_header():
    lwip_c = _read("LWIP/App/lwip.c")

    assert '#include "app_config.h"' not in lwip_c


def test_lwip_runtime_is_station_only_and_uses_single_sys_now_owner():
    lwip_c = _read("LWIP/App/lwip.c")
    sys_arch_c = _read(
        "Middlewares/Third_Party/SICS_Network_LwIP/LwIP/system/OS/sys_arch.c"
    )

    assert ".link_sta_up_fn = netif_link_sta_up_cb" in lwip_c
    assert ".link_sta_down_fn = netif_link_sta_down_cb" in lwip_c
    assert ".link_ap_up_fn = NULL" in lwip_c
    assert ".link_ap_down_fn = NULL" in lwip_c
    assert "ap_sta_ipv4_table_clear" not in lwip_c
    assert "wifi_ap_status_callback" not in lwip_c
    assert "u32_t sys_now(void)" not in lwip_c
    assert "u32_t sys_now(void)" in sys_arch_c


def test_wifi_config_selection_uses_compile_time_header_detection():
    cmake = _read("cmake/stm32cubemx/CMakeLists.txt")
    wrapper = _read("Core/Inc/pqc_wifi_config.h")

    assert "${CMAKE_BINARY_DIR}/pqc_generated" in cmake
    assert "PQC_WIFI_CONFIG_GENERATED_AVAILABLE" not in cmake
    assert 'if(EXISTS "${CMAKE_BINARY_DIR}/pqc_generated/pqc_wifi_config_generated.h")' not in cmake
    assert '#if defined(__has_include)' in wrapper
    assert '#  if __has_include("pqc_wifi_config_generated.h")' in wrapper
    assert '#    include "pqc_wifi_config_generated.h"' in wrapper
    assert 'PQC_WIFI_CONFIG_GENERATED_AVAILABLE' not in wrapper
    assert '#    define PQC_WIFI_SSID ""' in wrapper
    assert '#    define PQC_WIFI_IPV4_MODE "unconfigured"' in wrapper
    assert '#ifndef PQC_MQTT_TLS_MODE' in wrapper
    assert '#define PQC_MQTT_TLS_MODE "plaintext"' in wrapper
    assert '#ifndef PQC_MQTT_TLS_SERVER_NAME' in wrapper
    assert '#define PQC_MQTT_TLS_SERVER_NAME ""' in wrapper
    assert '#ifndef PQC_MQTT_TLS_CA_PEM' in wrapper
    assert '#define PQC_MQTT_TLS_CA_PEM ""' in wrapper
    assert '#ifndef PQC_MQTT_TLS_CA_PEM_SHA256' in wrapper
    assert '#define PQC_MQTT_TLS_CA_PEM_SHA256 ""' in wrapper
    assert '#ifndef PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM' in wrapper
    assert '#define PQC_MQTT_TLS_SERVER_SIGNATURE_ALGORITHM ""' in wrapper


def test_st67_normal_startup_scans_before_association_and_reports_live_t02_state() -> None:
    main_c = _read("Core/Src/main.c")

    scan_call = main_c.index("(void)APP_RunST67WiFiScan();")
    connect_call = main_c.index("status = W6X_WiFi_Connect(&options);")
    assert scan_call < connect_call
    assert "PQC_ST67_WIFI_DIAGNOSTIC_SCAN" not in main_c
    assert "diagnostic_scan=disabled" not in main_c
    assert "evidence=stm32-st67-t02-live-state" in main_c
    assert "network=available wifi=connected link=up ip=" in main_c

def test_st67_lwip_output_uses_vendor_segmented_pbuf_submission() -> None:
    netif_source = _read("LWIP/App/lwip_netif.c")

    assert "for (q = p_buf; q != NULL; q = q->next)" in netif_source
    assert "W6X_Netif_output(link_id, q->payload, q->len)" in netif_source
    assert "frame = pvPortMalloc(p_buf->tot_len);" not in netif_source
    assert "pbuf_copy_partial(p_buf, frame, p_buf->tot_len, 0U)" not in netif_source
    assert "W6X_Netif_output(link_id, frame, p_buf->tot_len)" not in netif_source


def test_st67_spi_iface_uses_clean_vendor_transfer_engine_for_controlled_test() -> None:
    spi_iface = _read(
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c"
    )

    assert '#include "stm32l4xx.h"' in spi_iface
    assert "static int32_t spi_do_xfer(struct spi_xfer_engine *engine, uint32_t flags)" in spi_iface
    assert "static void spi_xfer_engine_task(void *arg)" in spi_iface
    assert "while (true)" in spi_iface
    assert "APP_ST67ReadyDiagnosticSnapshot" not in spi_iface
    assert "APP_ST67ReadyDiagnosticSnapshotGet" not in spi_iface
    assert '#include "main.h"' not in spi_iface


def test_application_memory_checkpoints_report_named_task_stacks() -> None:
    main_c = _read("Core/Src/main.c")

    assert 'APP_UART_WriteString("application task stack: stage=");' in main_c
    assert 'APP_UART_WriteString(" task=");' in main_c
    assert 'APP_UART_WriteString(" minimum_free_bytes=");' in main_c
    assert 'APP_UART_WriteString(" peak_used_bytes=");' in main_c
    assert '"defaultTask",\n        (TaskHandle_t)defaultTaskHandle' in main_c
    assert '"networkTask",\n        (TaskHandle_t)networkTaskHandle' in main_c
    assert '(uint32_t)defaultTask_attributes.stack_size' in main_c
    assert '(uint32_t)networkTask_attributes.stack_size' in main_c
    assert "if (minimum_free_bytes <= task_stack_total_bytes)" in main_c
    assert 'APP_PrintApplicationMemoryCheckpoint("default_task_runtime", pdTRUE, pdFALSE);' in main_c
    assert 'APP_PrintApplicationMemoryCheckpoint("network_task_complete", pdTRUE, pdTRUE);' in main_c
    assert "task_stack_high_water_bytes" not in main_c
    assert "task_stack_used_bytes" not in main_c

def test_st67_spi_transaction_ready_wait_is_level_aware_and_race_safe() -> None:
    source = _read(
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c"
    )

    helper = _function_definition(
        source,
        "static int32_t spi_wait_txn_ready(struct spi_xfer_engine *engine)",
        "static int32_t spi_txrx(",
    )

    ready_checks = [
        index
        for index in range(len(helper))
        if helper.startswith("spi_port_is_ready() == 1", index)
    ]
    assert len(ready_checks) >= 2
    wait_index = helper.index(
        "xEventGroupWaitBits(engine->event, SPI_EVT_TXN_RDY,"
    )
    assert "pdTRUE, pdFALSE, remaining" in helper
    assert helper.index("spi_port_is_ready() == 1") < wait_index
    assert ready_checks[-1] > wait_index
    assert "spi_clear_event(engine, SPI_EVT_TXN_RDY)" in helper
    assert "(spi_wait_txn_ready(engine) == 0)" in source
    assert (
        "spi_wait_event(engine, SPI_EVT_TXN_RDY, SPI_WAIT_TXN_TIMEOUT_MS) == 0"
        not in source
    )

def test_st67_short_full_duplex_spi_transactions_use_polling_completion() -> None:
    source = _read(
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c"
    )

    txrx = _function_definition(
        source,
        "static int32_t spi_txrx(struct spi_xfer_engine *engine, void *tx_buf, void *rx_buf, uint16_t len)",
        "static int32_t spi_rx(",
    )

    assert "#define SPI_POLL_FULL_DUPLEX_MAX_BYTES  256U" in source
    assert (
        "if ((len <= SPI_DMA_XFER_SIZE_THRESHOLD) ||\n"
        "      (len <= SPI_POLL_FULL_DUPLEX_MAX_BYTES))"
        in txrx
    )
    assert (
        "spi_port_transfer(tx_buf, rx_buf, len, "
        "SPI_WAIT_POLL_XFER_TIMEOUT_MS)"
        in txrx
    )
    assert "spi_port_transfer_dma(tx_buf, rx_buf, len)" in txrx
    assert (
        'spi txrx transaction timeouted: mode=dma len=%" PRIu16'
        in txrx
    )


def test_st67_moderate_receive_only_spi_transactions_use_chunked_polling() -> None:
    source = _read(
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c"
    )

    rx = _function_definition(
        source,
        "static int32_t spi_rx(struct spi_xfer_engine *engine, void *rx_buf, uint16_t len)",
        "static int32_t spi_xfer_one(",
    )

    assert "#define SPI_POLL_RX_MAX_BYTES           2048U" in source
    assert "if (len <= SPI_POLL_RX_MAX_BYTES)" in rx
    assert "while (remaining > 0U)" in rx
    assert "if (chunk > SPI_DMA_XFER_SIZE_THRESHOLD)" in rx
    assert "chunk = SPI_DMA_XFER_SIZE_THRESHOLD;" in rx
    assert (
        "spi_port_transfer(NULL, rxp, chunk, "
        "SPI_WAIT_POLL_XFER_TIMEOUT_MS)"
        in rx
    )


def test_st67_large_receive_only_spi_transactions_remain_on_dma() -> None:
    source = _read(
        "Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c"
    )

    rx = _function_definition(
        source,
        "static int32_t spi_rx(struct spi_xfer_engine *engine, void *rx_buf, uint16_t len)",
        "static int32_t spi_xfer_one(",
    )

    assert "spi_port_transfer_dma(NULL, rx_buf, len)" in rx
    assert 'spi rx transaction timeouted: mode=dma len=%" PRIu16' in rx

