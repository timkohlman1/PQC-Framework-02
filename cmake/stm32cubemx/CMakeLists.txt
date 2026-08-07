cmake_minimum_required(VERSION 3.22)
# Enable CMake support for ASM and C languages
enable_language(C ASM)
# STM32CubeMX generated symbols (macros)
set(MX_Defines_Syms 
	ST67_ARCH=W6X_ARCH_T02 
	USE_HAL_DRIVER 
	STM32L4R5xx
    $<$<CONFIG:Debug>:DEBUG>
)

# STM32CubeMX generated include paths
set(MX_Include_Dirs
    ${CMAKE_BINARY_DIR}/pqc_generated
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Inc
    ${CMAKE_CURRENT_SOURCE_DIR}/../../ST67W6X/Target
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/App
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/Target
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/Target/arch
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Inc
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Inc/Legacy
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/CMSIS/Device/ST/STM32L4xx/Include
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/CMSIS/Include
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Api
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/netif/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/lwip/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/lwip/priv/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/lwip/prot/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/compat/stdc/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/compat/posix/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/compat/posix/sys/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/compat/posix/net/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/include/compat/posix/arpa/
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus
)

# STM32CubeMX generated application sources
set(MX_Application_Src
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/App/lwip.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/App/lwip_netif.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/App/dhcp_server_raw.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/App/http_client.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/App/altls_mbedtls.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../LWIP/App/sntp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../ST67W6X/Target/spi_port.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../ST67W6X/Target/util_task_port.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/main.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/freertos.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/stm32l4xx_it.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/stm32l4xx_hal_msp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/stm32l4xx_hal_timebase_tim.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/sysmem.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/syscalls.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../startup_stm32l4r5xx.s
)

# STM32 HAL/LL Drivers
set(STM32_Drivers_Src
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Core/Src/system_stm32l4xx.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_tim.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_tim_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_rcc.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_rcc_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_flash.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_flash_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_flash_ramfunc.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_gpio.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_i2c.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_i2c_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_dma.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_dma_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_pwr.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_pwr_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_cortex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_exti.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_uart.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_uart_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_spi.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Drivers/STM32L4xx_HAL_Driver/Src/stm32l4xx_hal_spi_ex.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at/modem_cmd_handler.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at/w61_at_ble.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at/w61_at_common.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at/w61_at_mqtt.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at/w61_at_net.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at/w61_at_sys.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_at/w61_at_wifi.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/w61_io.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Utils/Misc/common_parser.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Utils/Performance/iperf.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Utils/Performance/iperf_shell.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Utils/Performance/util_mem_perf.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Utils/Performance/util_task_perf.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Utils/Performance/wfa_tg.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Utils/Logging/logging.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_ble.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_http.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_mqtt.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_net.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_netif.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_sys.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Core/w6x_wifi.c
)

# Drivers Midllewares


set(FreeRTOS_Src
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/croutine.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/event_groups.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/list.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/queue.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/stream_buffer.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/tasks.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/timers.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/CMSIS_RTOS_V2/cmsis_os2.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/portable/MemMang/heap_4.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F/port.c
)
# The STM32 firmware uses Ethernet-style IPv4 over the ST67 netif. IPv6,
# bridge, PPP/PPPoE/PPPoS/L2TP, and SLIP translation units are excluded from
# the target rather than relying only on disabled lwIP feature macros.
set(LwIP_Src
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/api_lib.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/api_msg.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/err.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/if_api.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/netbuf.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/netdb.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/netifapi.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/sockets.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/api/tcpip.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/acd.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/autoip.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/dhcp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/etharp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/icmp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/igmp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/ip4.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/ip4_addr.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ipv4/ip4_frag.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/altcp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/altcp_tcp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/def.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/dns.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/inet_chksum.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/init.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/ip.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/mem.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/memp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/netif.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/pbuf.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/raw.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/stats.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/sys.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/tcp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/tcp_in.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/tcp_out.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/timeouts.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/core/udp.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/src/netif/ethernet.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/Third_Party/SICS_Network_LwIP/LwIP/system/OS/sys_arch.c
)


# Phase M5 compile/link-only integration keeps generated lwIP/ST67W6X
# middleware sources available for STM32 builds while excluding generated
# runtime applications and optional protocol/demo utilities that require a
# real network backend or application-specific headers.
list(FILTER MX_Application_Src EXCLUDE REGEX "/LWIP/App/(altls_mbedtls|sntp|dhcp_server_raw|http_client)\\.c$")
list(FILTER STM32_Drivers_Src EXCLUDE REGEX "/Utils/Performance/")
list(FILTER STM32_Drivers_Src EXCLUDE REGEX "/Core/w6x_(ble|http|mqtt)\\.c$")
set_source_files_properties(
    ${CMAKE_CURRENT_SOURCE_DIR}/../../Middlewares/ST/ST67W6X_Network_Driver/Driver/W61_bus/spi_iface.c
    PROPERTIES COMPILE_OPTIONS "-include;stdint.h;-include;cmsis_gcc.h"
)

# Link directories setup
set(MX_LINK_DIRS

)
# Project static libraries
set(MX_LINK_LIBS 
    STM32_Drivers
    ${TOOLCHAIN_LINK_LIBRARIES}
    FreeRTOS
	LwIP
	
)
# Interface library for includes and symbols
add_library(stm32cubemx INTERFACE)
target_include_directories(stm32cubemx INTERFACE ${MX_Include_Dirs})
target_compile_definitions(stm32cubemx INTERFACE ${MX_Defines_Syms})

# Create STM32_Drivers static library
add_library(STM32_Drivers OBJECT)
target_sources(STM32_Drivers PRIVATE ${STM32_Drivers_Src})
target_link_libraries(STM32_Drivers PUBLIC stm32cubemx)


# Create FreeRTOS static library
add_library(FreeRTOS OBJECT)
target_sources(FreeRTOS PRIVATE ${FreeRTOS_Src})
target_link_libraries(FreeRTOS PUBLIC stm32cubemx)

# Create LwIP static library
add_library(LwIP OBJECT)
target_sources(LwIP PRIVATE ${LwIP_Src})
target_link_libraries(LwIP PUBLIC stm32cubemx)

# Add STM32CubeMX generated application sources to the project
target_sources(${CMAKE_PROJECT_NAME} PRIVATE ${MX_Application_Src})

# The root CMakeLists.txt owns STM32 MQTT workload selection and adds exactly
# one application implementation to the executable. This CubeMX integration
# layer must not register an application entry point independently, otherwise
# legacy and selected workloads can both define PQC_MQTT_ApplicationRun().

if(PQC_UART_LOG_LEVEL STREQUAL "error")
    set(PQC_UART_LOG_LEVEL_VALUE 0)
elseif(PQC_UART_LOG_LEVEL STREQUAL "info")
    set(PQC_UART_LOG_LEVEL_VALUE 1)
elseif(PQC_UART_LOG_LEVEL STREQUAL "debug")
    set(PQC_UART_LOG_LEVEL_VALUE 2)
else()
    message(FATAL_ERROR "Unsupported UART log level: ${PQC_UART_LOG_LEVEL}")
endif()

target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    PQC_STM32_MQTT_APPLICATION_NAME="${PQC_STM32_MQTT_APPLICATION}"
    PQC_UART_LOG_LEVEL=${PQC_UART_LOG_LEVEL_VALUE}
)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE ${MX_LINK_DIRS})

# Add libraries to the project
target_link_libraries(${CMAKE_PROJECT_NAME} ${MX_LINK_LIBS})

# Add the map file to the list of files to be removed with 'clean' target
set_target_properties(${CMAKE_PROJECT_NAME} PROPERTIES ADDITIONAL_CLEAN_FILES ${CMAKE_PROJECT_NAME}.map)

# Validate that STM32CubeMX code is compatible with C standard
if((CMAKE_C_STANDARD EQUAL 90) OR (CMAKE_C_STANDARD EQUAL 99))
    message(ERROR "Generated code requires C11 or higher")
endif()
