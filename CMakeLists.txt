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
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME stm32_basic_hal1)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Select the linker script and vector-table offset for the requested build profile.
#
# The default Debug/Release presets keep the CubeMX direct-flash layout at
# 0x08000000. The RelocatedDebug preset overrides these cache variables to build
# the HAL application for wolfBoot handoff at 0x08022000 using the shared Phase 11 8 KB image-header reserve.
set(STM32_LINKER_SCRIPT
    "${CMAKE_SOURCE_DIR}/STM32L4R5XX_FLASH.ld"
    CACHE FILEPATH
    "Linker script used for this STM32 firmware build"
)
set(STM32_APP_VECTOR_OFFSET
    "0x00000000"
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
set(PQC_TLS_ENABLE_MLKEM_768 0 CACHE BOOL "Compile ML-KEM-768 hybrid key exchange")
set(PQC_TLS_SELECTION_FILE "${CMAKE_BINARY_DIR}/pqc_generated/pqc_tls_algorithm_selection.cmake")
if(EXISTS "${PQC_TLS_SELECTION_FILE}")
    include("${PQC_TLS_SELECTION_FILE}")
endif()
message("TLS algorithm mode: " ${PQC_TLS_ALGORITHM_MODE})
message("TLS RSA/RSA-PSS: " ${PQC_TLS_ENABLE_RSA} "/" ${PQC_TLS_ENABLE_RSA_PSS})
message("TLS ML-KEM-768: " ${PQC_TLS_ENABLE_MLKEM_768})


# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Phase M6.1 wolfSSL TLS-context lifecycle source integration.
#
# Reuse the wolfSSL source tree carried by the wolfBoot submodule. The selected
# source set is limited to wolfSSL client-context and supporting wolfCrypt code
# needed to initialize wolfSSL, create/free a TLS 1.2 client WOLFSSL_CTX, and
# clean up global state. No transport, certificate loading, handshake, MQTT,
# Wi-Fi, or ST67W61M1 backend is enabled by this target.
set(PQC_WOLFSSL_SOURCE_DIR
    "${CMAKE_SOURCE_DIR}/tools/wolfboot/lib/wolfssl"
    CACHE PATH
    "Repository-local wolfSSL source directory used for Phase M6.1 STM32 TLS-context smoke coverage"
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
    "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/ecc.c"
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

if(PQC_TLS_ENABLE_RSA)
    list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/rsa.c"
    )
endif()

if(PQC_TLS_ENABLE_MLKEM_768)
    list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/sha3.c"
    )
endif()

if(PQC_TLS_ENABLE_MLKEM_768)
    list(APPEND PQC_WOLFSSL_TLS_CONTEXT_SOURCES
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/wc_mlkem.c"
        "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/wc_mlkem_poly.c"
    )
endif()


foreach(PQC_WOLFSSL_SOURCE IN LISTS PQC_WOLFSSL_TLS_CONTEXT_SOURCES)
    if(NOT EXISTS "${PQC_WOLFSSL_SOURCE}")
        message(FATAL_ERROR
            "Phase M6.1 wolfSSL source file not found: ${PQC_WOLFSSL_SOURCE}. "
            "Initialise or update the wolfBoot submodule so tools/wolfboot/lib/wolfssl is available."
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
    PQC_TLS_ENABLE_MLKEM_768=$<BOOL:${PQC_TLS_ENABLE_MLKEM_768}>
)



# Phase M7 wolfMQTT build-only source integration.
#
# wolfMQTT is maintained as its own pinned repository submodule. The project
# builds the core MQTT client, packet, and socket callback layers only. TLS is
# intentionally disabled here; the existing project-owned wolfSSL transport
# boundary remains unavailable until a later network-backed phase.
set(PQC_WOLFMQTT_SOURCE_DIR
    "${CMAKE_SOURCE_DIR}/Middlewares/Third_Party/wolfMQTT"
    CACHE PATH
    "Repository-local wolfMQTT source directory used for Phase M7 STM32 build-only coverage"
)

set(PQC_WOLFMQTT_BUILD_ONLY_SOURCES
    "${PQC_WOLFMQTT_SOURCE_DIR}/src/mqtt_client.c"
    "${PQC_WOLFMQTT_SOURCE_DIR}/src/mqtt_packet.c"
    "${PQC_WOLFMQTT_SOURCE_DIR}/src/mqtt_socket.c"
)

foreach(PQC_WOLFMQTT_SOURCE IN LISTS PQC_WOLFMQTT_BUILD_ONLY_SOURCES)
    if(NOT EXISTS "${PQC_WOLFMQTT_SOURCE}")
        message(FATAL_ERROR
            "Phase M7 wolfMQTT source file not found: ${PQC_WOLFMQTT_SOURCE}. "
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
    "${PQC_WOLFSSL_SOURCE_DIR}"
)

target_compile_definitions(pqc_wolfmqtt_stm32_build_only PUBLIC
    BUILDING_WOLFMQTT
    WOLFMQTT_USER_SETTINGS
    WOLFMQTT_NO_STDIO
)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Src/pqc_lwip_build_only.c
    Core/Src/pqc_network_interface.c
    Core/Src/pqc_wolfssl_build_only.c
    Core/Src/pqc_wolfssl_transport.c
    Core/Src/pqc_wolfmqtt_build_only.c
    # Add user sources here
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Inc
    "${PQC_WOLFSSL_SOURCE_DIR}"
    "${PQC_WOLFMQTT_SOURCE_DIR}"
    # Add user defined include paths
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    PQC_WOLFSSL_BUILD_ONLY=1
    WOLFSSL_USER_SETTINGS
    PQC_STM32_APP_WOLFSSL_USER_SETTINGS=1
    PQC_WOLFSSL_SOURCE_BUILD=1
    PQC_TLS_ENABLE_RSA=$<BOOL:${PQC_TLS_ENABLE_RSA}>
    PQC_TLS_ENABLE_RSA_PSS=$<BOOL:${PQC_TLS_ENABLE_RSA_PSS}>
    PQC_TLS_ENABLE_MLKEM_768=$<BOOL:${PQC_TLS_ENABLE_MLKEM_768}>
    WOLFMQTT_USER_SETTINGS
    WOLFMQTT_NO_STDIO
    USER_VECT_TAB_ADDRESS
    VECT_TAB_OFFSET=${STM32_APP_VECTOR_OFFSET}
    # Add user defined symbols
)

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
    pqc_wolfssl_stm32_build_only
    pqc_wolfmqtt_stm32_build_only

    # Add user defined libraries
)
