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

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Phase M6 wolfSSL source build integration.
#
# Reuse the wolfSSL source tree carried by the wolfBoot submodule, but keep all
# project-specific configuration in Core/Inc/user_settings.h and the
# pqc_wolfssl_build_only boundary. This target intentionally builds only the
# wolfCrypt SHA-256 source needed by the STM32 build-only smoke check. It does
# not build or run a TLS transport, certificate loader, MQTT client, or
# ST67W61M1 backend.
set(PQC_WOLFSSL_SOURCE_DIR
    "${CMAKE_SOURCE_DIR}/tools/wolfboot/lib/wolfssl"
    CACHE PATH
    "Repository-local wolfSSL source directory used for Phase M6 STM32 build-only smoke coverage"
)

set(PQC_WOLFSSL_SHA256_SOURCE "${PQC_WOLFSSL_SOURCE_DIR}/wolfcrypt/src/sha256.c")
if(NOT EXISTS "${PQC_WOLFSSL_SHA256_SOURCE}")
    message(FATAL_ERROR
        "Phase M6 wolfSSL source file not found: ${PQC_WOLFSSL_SHA256_SOURCE}. "
        "Initialise or update the wolfBoot submodule so tools/wolfboot/lib/wolfssl is available."
    )
endif()

add_library(pqc_wolfssl_stm32_build_only STATIC
    "${PQC_WOLFSSL_SHA256_SOURCE}"
)

target_include_directories(pqc_wolfssl_stm32_build_only PUBLIC
    Core/Inc
    "${PQC_WOLFSSL_SOURCE_DIR}"
)

target_compile_definitions(pqc_wolfssl_stm32_build_only PUBLIC
    WOLFSSL_USER_SETTINGS
    PQC_WOLFSSL_SOURCE_BUILD=1
)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Src/pqc_lwip_build_only.c
    Core/Src/pqc_wolfssl_build_only.c
    # Add user sources here
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Inc
    "${PQC_WOLFSSL_SOURCE_DIR}"
    # Add user defined include paths
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    PQC_WOLFSSL_BUILD_ONLY=1
    PQC_WOLFSSL_SOURCE_BUILD=1
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

    # Add user defined libraries
)
