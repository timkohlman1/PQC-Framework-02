cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)


# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Release")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME stm32_basic_hal1)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})


option(PQC_WOLFSSL_MEMORY_DIAGNOSTICS
    "Enable wolfSSL heap/failure UART diagnostics (changes timing)" OFF)
option(PQC_WOLFSSL_ALLOCATION_PROVENANCE
    "Enable wolfSSL allocation source/type UART tracing (changes timing)" OFF)
option(PQC_TIMEBASE_HARDWARE_SELF_TEST
    "Enable a pre-workload 10 ms TIM2/HAL tick comparison marker for hardware validation" OFF)
set(PQC_MLDSA_WORKSPACE_SIZE_BYTES "98304" CACHE STRING
    "Dedicated RAM3 ML-DSA scratch workspace size in bytes")

if(PQC_WOLFSSL_ALLOCATION_PROVENANCE)
    set(PQC_WOLFSSL_MEMORY_DIAGNOSTICS ON CACHE BOOL
        "Enable wolfSSL heap/failure UART diagnostics (changes timing)" FORCE)
endif()

message("Build type: " ${CMAKE_BUILD_TYPE})

# Select the linker script and vector-table offset for the requested build profile.
#
# Debug and Release both use the fixed wolfBoot-relocated application layout.
# Release is the default build type; Debug changes compiler settings only.
set(STM32_LINKER_SCRIPT
    "${CMAKE_SOURCE_DIR}/STM32L4R5XX_FLASH_RELOCATED.ld"
    CACHE FILEPATH
    "Linker script used for this STM32 firmware build"
)
set(STM32_APP_VECTOR_OFFSET
    "0x00023000"
    CACHE STRING
    "Vector table offset from FLASH_BASE for this STM32 firmware build"
)

if(NOT EXISTS "${STM32_LINKER_SCRIPT}")
    message(FATAL_ERROR "STM32 linker script not found: ${STM32_LINKER_SCRIPT}")
endif()

message("STM32 linker script: " ${STM32_LINKER_SCRIPT})
message("STM32 vector table offset: " ${STM32_APP_VECTOR_OFFSET})

# Enable CMake support for ASM and C languages
enable_language(C ASM)

# Experiment builds generate this file before CMake configure. Direct CMake
# invocations default to the minimal classical RSA TLS 1.3 capability set.
set(PQC_TLS_ALGORITHM_MODE "classical" CACHE STRING "Resolved TLS algorithm mode")
set(PQC_TLS_ENABLE_RSA 1 CACHE BOOL "Compile RSA certificate verification")
set(PQC_TLS_ENABLE_RSA_PSS 1 CACHE BOOL "Compile and advertise RSA-PSS")
set(PQC_TLS_ENABLE_ECC 1 CACHE BOOL "Compile prime-curve ECC key exchange")
set(PQC_TLS_ENABLE_CERT_ECC 0 CACHE BOOL "Compile ECC for X.509 certificate parsing and verification")
set(PQC_TLS_CERT_ECC_BITS 0 CACHE STRING "Selected ECC certificate key size; 0 when not applicable")
set(PQC_TLS_ENABLE_SHA384 0 CACHE BOOL "Compile SHA-384 for certificate signatures that require it")
set(PQC_TLS_ECC_MIN_BITS 256 CACHE STRING "Minimum accepted ECC key size across KEX and certificates")
set(PQC_TLS_ECC_BITS 256 CACHE STRING "Selected prime-curve KEX size")
set(PQC_TLS_ENABLE_CURVE25519 0 CACHE BOOL "Compile X25519 key exchange")
set(PQC_TLS_ENABLE_MLKEM_512 0 CACHE BOOL "Compile ML-KEM-512 key exchange")
set(PQC_TLS_ENABLE_MLKEM_768 0 CACHE BOOL "Compile ML-KEM-768 key exchange")
set(PQC_TLS_ENABLE_MLKEM_1024 0 CACHE BOOL "Compile ML-KEM-1024 key exchange")
set(PQC_TLS_MLKEM_STANDALONE 0 CACHE BOOL "Enable standalone ML-KEM TLS groups")
set(PQC_TLS_ENABLE_MLDSA_65 0 CACHE BOOL "Compile ML-DSA-65 certificate verification")
set(PQC_TLS_ENABLE_MLDSA_65_SIGN 0 CACHE BOOL "Compile ML-DSA-65 client CertificateVerify signing")
set(PQC_TLS_GROUP_ID WOLFSSL_ECC_SECP256R1 CACHE STRING "wolfSSL named-group token")
set(PQC_TLS_GROUP_NAME secp256r1 CACHE STRING "TLS named-group display name")
set(PQC_TLS_SELECTION_FILE "${CMAKE_BINARY_DIR}/pqc_generated/pqc_tls_algorithm_selection.cmake")
if(EXISTS "${PQC_TLS_SELECTION_FILE}")
    include("${PQC_TLS_SELECTION_FILE}")
endif()

if(PQC_TLS_ALGORITHM_MODE STREQUAL "plaintext")
    set(PQC_TLS_COMPILED 0)
else()
    set(PQC_TLS_COMPILED 1)
endif()

message("TLS compiled: " ${PQC_TLS_COMPILED})
message("TLS algorithm mode: " ${PQC_TLS_ALGORITHM_MODE})
message("TLS RSA/RSA-PSS: " ${PQC_TLS_ENABLE_RSA} "/" ${PQC_TLS_ENABLE_RSA_PSS})
message("TLS group: " ${PQC_TLS_GROUP_NAME} " (" ${PQC_TLS_GROUP_ID} ")")
message("TLS key-exchange ECC/Curve25519: " ${PQC_TLS_ENABLE_ECC} "/" ${PQC_TLS_ENABLE_CURVE25519})
message("TLS certificate ECC/bits/minimum bits: " ${PQC_TLS_ENABLE_CERT_ECC} "/" ${PQC_TLS_CERT_ECC_BITS} "/" ${PQC_TLS_ECC_MIN_BITS})
message("TLS SHA-384: " ${PQC_TLS_ENABLE_SHA384})
message("TLS ML-KEM-512/768/1024 standalone: " ${PQC_TLS_ENABLE_MLKEM_512} "/" ${PQC_TLS_ENABLE_MLKEM_768} "/" ${PQC_TLS_ENABLE_MLKEM_1024} " standalone=" ${PQC_TLS_MLKEM_STANDALONE})
message("TLS ML-DSA-65 verification/signing: " ${PQC_TLS_ENABLE_MLDSA_65} "/" ${PQC_TLS_ENABLE_MLDSA_65_SIGN})

set(PQC_STM32_MQTT_APPLICATION "mqtt_validation")
set(PQC_UART_LOG_LEVEL "info")
set(PQC_UART_OUTPUT_MODE "minimal")
set(PQC_FIRMWARE_MODE "single_bank")
set(PQC_DUAL_BANK_ENABLED 0)
set(PQC_OTA_ENABLED 0)
set(PQC_STANDBY_SIGNING_KEYS 0)
set(PQC_APPLICATION_SELECTION_FILE "${CMAKE_BINARY_DIR}/pqc_generated/pqc_application_selection.cmake")
if(EXISTS "${PQC_APPLICATION_SELECTION_FILE}")
    include("${PQC_APPLICATION_SELECTION_FILE}")
endif()
if(PQC_STM32_MQTT_APPLICATION STREQUAL "mqtt_validation")
    set(PQC_STM32_MQTT_APPLICATION_SOURCE Core/Src/pqc_mqtt_application_mqtt_validation.c)
elseif(PQC_STM32_MQTT_APPLICATION STREQUAL "mqtt_ready_metrics")
    set(PQC_STM32_MQTT_APPLICATION_SOURCE Core/Src/pqc_mqtt_application_ready_metrics.c)
elseif(PQC_STM32_MQTT_APPLICATION STREQUAL "mqtt_ready_metrics_2")
    set(PQC_STM32_MQTT_APPLICATION_SOURCE Core/Src/pqc_mqtt_application_ready_metrics_2.c)
else()
    message(FATAL_ERROR "Unsupported STM32 MQTT application: ${PQC_STM32_MQTT_APPLICATION}")
endif()
message("STM32 MQTT application: " ${PQC_STM32_MQTT_APPLICATION})
if(NOT PQC_FIRMWARE_MODE STREQUAL "single_bank" AND
   NOT PQC_FIRMWARE_MODE STREQUAL "dual_bank_no_ota" AND
   NOT PQC_FIRMWARE_MODE STREQUAL "dual_bank_ota")
    message(FATAL_ERROR "Unsupported PQC_FIRMWARE_MODE: ${PQC_FIRMWARE_MODE}")
endif()
if(PQC_OTA_ENABLED AND NOT PQC_DUAL_BANK_ENABLED)
    message(FATAL_ERROR "PQC_OTA_ENABLED requires PQC_DUAL_BANK_ENABLED")
endif()
if(PQC_STANDBY_SIGNING_KEYS LESS 0 OR PQC_STANDBY_SIGNING_KEYS GREATER 2)
    message(FATAL_ERROR "PQC_STANDBY_SIGNING_KEYS must be 0, 1, or 2")
endif()
message("Firmware mode: " ${PQC_FIRMWARE_MODE})
message("Dual-bank compiled: " ${PQC_DUAL_BANK_ENABLED})
message("OTA compiled: " ${PQC_OTA_ENABLED})
message("Standby signing keys: " ${PQC_STANDBY_SIGNING_KEYS})


# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# STM32 wolfSSL TLS 1.3 runtime source integration.
#
# Use the project-controlled top-level wolfSSL submodule. The selected
# source set provides the profile-selected TLS 1.3 client, certificate
# verification, key exchange, and wolfCrypt primitives used by the project-owned
# lwIP/ST67 transport and wolfMQTT runtime path. TLS capabilities remain
# profile-selected through the generated algorithm configuration below.
if(PQC_TLS_COMPILED)
    set(PQC_WOLFSSL_SOURCE_DIR
        "${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/wolfSSL"
        CACHE PATH
        "Repository-local wolfSSL source directory used for STM32 TLS 1.3 runtime"
    )

    set(PQC_WOLFSSL_TLS_CONTEXT_SOURCES
        "${PQC_WOLFSSL_SOURCE_DIR}/src/internal.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/src/keys.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/src/ssl.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/src/tls.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/src/tls13.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/src/wolfio.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/aes.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/asn.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/coding.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/hash.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/hmac.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/kdf.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/logging.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/memory.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/random.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/sha256.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/sp_int.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/wc_port.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/wolfmath.c"
    )


    if(PQC_TLS_ENABLE_ECC OR PQC_TLS_ENABLE_CERT_ECC)
        list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/ecc.c"
        )
    endif()

    if(PQC_TLS_ENABLE_SHA384)
        list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/sha512.c"
        )
    endif()

    if(PQC_TLS_ENABLE_CURVE25519)
        list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/curve25519.c"
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/fe_low_mem.c"
        )
    endif()

    if(PQC_TLS_ENABLE_RSA)
        list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/rsa.c"
        )
    endif()

    if(PQC_TLS_ENABLE_MLKEM_512 OR PQC_TLS_ENABLE_MLKEM_768 OR PQC_TLS_ENABLE_MLKEM_1024 OR PQC_TLS_ENABLE_MLDSA_65)
        list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/sha3.c"
        )
    endif()

    if(PQC_TLS_ENABLE_MLKEM_512 OR PQC_TLS_ENABLE_MLKEM_768 OR PQC_TLS_ENABLE_MLKEM_1024)
        list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/wc_mlkem.c"
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/wc_mlkem_poly.c"
        )
    endif()

    if(PQC_TLS_ENABLE_MLDSA_65)
        list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
            "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/wc_mldsa.c"
        )
    endif()


    foreach(PQC_WOLFSSL_SOURCE IN LISTS PQC_WOLFSSL_TLS_CONTEXT_SOURCES)
        if(NOT EXISTS "${PQC_WOLFSSL_SOURCE}")
            message(FATAL_ERROR
                "wolfSSL source file not found: ${PQC_WOLFSSL_SOURCE}. "
                "Initialise or update the Middlewares/Third_Party/wolfSSL submodule."
            )
        endif()
    endforeach()

    add_library(pqc_wolfssl_stm32_build_only STATIC
        ${PQC_WOLFSSL_TLS_CONTEXT_SOURCES}
    )

    target_include_directories(pqc_wolfssl_stm32_build_only PUBLIC
        Core/Inc
        "${PQC_WOLFSSL_SOURCE_DIR}"
    )

    target_compile_definitions(pqc_wolfssl_stm32_build_only PUBLIC
        WOLFSSL_USER_SETTINGS
        PQC_STM32_APP_WOLFSSL_USER_SETTINGS=1
        PQC_WOLFSSL_SOURCE_BUILD=1
        PQC_TLS_ENABLE_RSA=$<BOOL:${PQC_TLS_ENABLE_RSA}>
        PQC_TLS_ENABLE_RSA_PSS=$<BOOL:${PQC_TLS_ENABLE_RSA_PSS}>
        PQC_TLS_ENABLE_ECC=$<BOOL:${PQC_TLS_ENABLE_ECC}>
        PQC_TLS_ENABLE_CERT_ECC=$<BOOL:${PQC_TLS_ENABLE_CERT_ECC}>
        PQC_TLS_ECC_MIN_BITS=${PQC_TLS_ECC_MIN_BITS}
        PQC_TLS_ECC_BITS=${PQC_TLS_ECC_BITS}
        PQC_TLS_CERT_ECC_BITS=${PQC_TLS_CERT_ECC_BITS}
        PQC_TLS_ENABLE_SHA384=$<BOOL:${PQC_TLS_ENABLE_SHA384}>
        PQC_TLS_ENABLE_CURVE25519=$<BOOL:${PQC_TLS_ENABLE_CURVE25519}>
        PQC_TLS_ENABLE_MLKEM_512=$<BOOL:${PQC_TLS_ENABLE_MLKEM_512}>
        PQC_TLS_ENABLE_MLKEM_768=$<BOOL:${PQC_TLS_ENABLE_MLKEM_768}>
        PQC_TLS_ENABLE_MLKEM_1024=$<BOOL:${PQC_TLS_ENABLE_MLKEM_1024}>
        PQC_TLS_MLKEM_STANDALONE=$<BOOL:${PQC_TLS_MLKEM_STANDALONE}>
        PQC_TLS_ENABLE_MLDSA_65=$<BOOL:${PQC_TLS_ENABLE_MLDSA_65}>
        PQC_TLS_ENABLE_MLDSA_65_SIGN=$<BOOL:${PQC_TLS_ENABLE_MLDSA_65_SIGN}>
        PQC_TLS_GROUP_ID=${PQC_TLS_GROUP_ID}
        PQC_TLS_GROUP_NAME=\"${PQC_TLS_GROUP_NAME}\"
        PQC_TLS_INSTRUMENTATION=1
        PQC_WOLFSSL_MEMORY_DIAGNOSTICS=$<BOOL:${PQC_WOLFSSL_MEMORY_DIAGNOSTICS}>
        PQC_WOLFSSL_ALLOCATION_PROVENANCE=$<BOOL:${PQC_WOLFSSL_ALLOCATION_PROVENANCE}>
        PQC_MLDSA_WORKSPACE_SIZE_BYTES=${PQC_MLDSA_WORKSPACE_SIZE_BYTES}
    )
endif()



# STM32 wolfMQTT core source integration.
#
# wolfMQTT is maintained as its own pinned repository submodule. The project
# builds the core MQTT client, packet, and socket callback layers while the
# project-owned network wrapper supplies the lwIP/ST67 transport and, for TLS
# profiles, the wolfSSL TLS 1.3 session used beneath wolfMQTT.
set(PQC_WOLFMQTT_SOURCE_DIR
    "${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/wolfMQTT"
    CACHE PATH
    "Repository-local wolfMQTT source directory used by the STM32 MQTT runtime"
)

set(PQC_WOLFMQTT_BUILD_ONLY_SOURCES
    "${PQC_WOLFMQTT_SOURCE_DIR}/src/mqtt_client.c"
    "${PQC_WOLFMQTT_SOURCE_DIR}/src/mqtt_packet.c"
    "${PQC_WOLFMQTT_SOURCE_DIR}/src/mqtt_socket.c"
)

foreach(PQC_WOLFMQTT_SOURCE IN LISTS PQC_WOLFMQTT_BUILD_ONLY_SOURCES)
    if(NOT EXISTS "${PQC_WOLFMQTT_SOURCE}")
        message(FATAL_ERROR
            "wolfMQTT source file not found: ${PQC_WOLFMQTT_SOURCE}. "
            "Initialise the Middlewares/Third_Party/wolfMQTT submodule."
        )
    endif()
endforeach()

add_library(pqc_wolfmqtt_stm32_build_only STATIC
    ${PQC_WOLFMQTT_BUILD_ONLY_SOURCES}
)

target_include_directories(pqc_wolfmqtt_stm32_build_only PUBLIC
    Core/Inc
    "${PQC_WOLFMQTT_SOURCE_DIR}"
)

if(PQC_TLS_COMPILED)
    target_include_directories(pqc_wolfmqtt_stm32_build_only PUBLIC
        "${PQC_WOLFSSL_SOURCE_DIR}"
    )
endif()

target_compile_definitions(pqc_wolfmqtt_stm32_build_only PUBLIC
    BUILDING_WOLFMQTT
    WOLFMQTT_USER_SETTINGS
    WOLFMQTT_NO_STDIO
    PQC_DUAL_BANK_ENABLED=${PQC_DUAL_BANK_ENABLED}
    PQC_OTA_ENABLED=${PQC_OTA_ENABLED}
    PQC_STANDBY_SIGNING_KEYS=${PQC_STANDBY_SIGNING_KEYS}
    PQC_TIMEBASE_HARDWARE_SELF_TEST=$<BOOL:${PQC_TIMEBASE_HARDWARE_SELF_TEST}>
)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Src/pqc_lwip_build_only.c
    Core/Src/pqc_network_interface.c
    Core/Src/pqc_wolfmqtt_build_only.c
    Core/Src/pqc_tls_instrumentation.c
    Core/Src/pqc_timebase.c
    Core/Src/pqc_result_buffer.c
    ${PQC_STM32_MQTT_APPLICATION_SOURCE}
    # Add user sources here
)

if(PQC_TLS_COMPILED)
    target_sources(${CMAKE_PROJECT_NAME} PRIVATE
        Core/Src/pqc_wolfssl_build_only.c
        Core/Src/pqc_wolfssl_transport.c
        Core/Src/pqc_wolfssl_memory.c
    )

target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    PQC_WOLFSSL_MEMORY_DIAGNOSTICS=$<BOOL:${PQC_WOLFSSL_MEMORY_DIAGNOSTICS}>
    PQC_WOLFSSL_ALLOCATION_PROVENANCE=$<BOOL:${PQC_WOLFSSL_ALLOCATION_PROVENANCE}>
    PQC_MLDSA_WORKSPACE_SIZE_BYTES=${PQC_MLDSA_WORKSPACE_SIZE_BYTES}
)
endif()

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Inc
    "${PQC_WOLFMQTT_SOURCE_DIR}"
    # Add user defined include paths
)

if(PQC_TLS_COMPILED)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
        "${PQC_WOLFSSL_SOURCE_DIR}"
    )
endif()

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    PQC_TLS_COMPILED=${PQC_TLS_COMPILED}
    PQC_DUAL_BANK_ENABLED=${PQC_DUAL_BANK_ENABLED}
    PQC_OTA_ENABLED=${PQC_OTA_ENABLED}
    PQC_STANDBY_SIGNING_KEYS=${PQC_STANDBY_SIGNING_KEYS}
    WOLFMQTT_USER_SETTINGS
    WOLFMQTT_NO_STDIO
    USER_VECT_TAB_ADDRESS
    VECT_TAB_OFFSET=${STM32_APP_VECTOR_OFFSET}
    # Add user defined symbols
)

if(PQC_TLS_COMPILED)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
        WOLFSSL_USER_SETTINGS
        PQC_STM32_APP_WOLFSSL_USER_SETTINGS=1
        PQC_WOLFSSL_SOURCE_BUILD=1
        PQC_TLS_ENABLE_RSA=$<BOOL:${PQC_TLS_ENABLE_RSA}>
        PQC_TLS_ENABLE_RSA_PSS=$<BOOL:${PQC_TLS_ENABLE_RSA_PSS}>
        PQC_TLS_ENABLE_ECC=$<BOOL:${PQC_TLS_ENABLE_ECC}>
        PQC_TLS_ENABLE_CERT_ECC=$<BOOL:${PQC_TLS_ENABLE_CERT_ECC}>
        PQC_TLS_ECC_MIN_BITS=${PQC_TLS_ECC_MIN_BITS}
        PQC_TLS_ECC_BITS=${PQC_TLS_ECC_BITS}
        PQC_TLS_CERT_ECC_BITS=${PQC_TLS_CERT_ECC_BITS}
        PQC_TLS_ENABLE_SHA384=$<BOOL:${PQC_TLS_ENABLE_SHA384}>
        PQC_TLS_ENABLE_CURVE25519=$<BOOL:${PQC_TLS_ENABLE_CURVE25519}>
        PQC_TLS_ENABLE_MLKEM_512=$<BOOL:${PQC_TLS_ENABLE_MLKEM_512}>
        PQC_TLS_ENABLE_MLKEM_768=$<BOOL:${PQC_TLS_ENABLE_MLKEM_768}>
        PQC_TLS_ENABLE_MLKEM_1024=$<BOOL:${PQC_TLS_ENABLE_MLKEM_1024}>
        PQC_TLS_MLKEM_STANDALONE=$<BOOL:${PQC_TLS_MLKEM_STANDALONE}>
        PQC_TLS_ENABLE_MLDSA_65=$<BOOL:${PQC_TLS_ENABLE_MLDSA_65}>
        PQC_TLS_ENABLE_MLDSA_65_SIGN=$<BOOL:${PQC_TLS_ENABLE_MLDSA_65_SIGN}>
        PQC_TLS_GROUP_ID=${PQC_TLS_GROUP_ID}
        PQC_TLS_GROUP_NAME=\"${PQC_TLS_GROUP_NAME}\"
    )
endif()

if(NOT STM32_APP_VECTOR_OFFSET STREQUAL "0x00000000")
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
        SECURE_BOOT_APPLICATION
    )
endif()

# The selected STM32 linker script is consumed by cmake/gcc-arm-none-eabi.cmake.
# Keep linker-script selection in one place so the direct-flash and relocated
# presets do not pass duplicate -T options to the linker.

# Remove wrong libob.a library dependency when using cpp files
list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx
    pqc_wolfmqtt_stm32_build_only

    # Add user defined libraries
)

if(PQC_TLS_COMPILED)
    target_link_libraries(${CMAKE_PROJECT_NAME}
        pqc_wolfssl_stm32_build_only
    )
endif()
