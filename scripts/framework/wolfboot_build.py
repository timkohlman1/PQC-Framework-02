"""wolfBoot build-profile helpers.

This module runs a configured local wolfBoot build and records build evidence.
It does not flash hardware, open UART devices, use SSH, sign application images,
or copy private signing keys into result directories.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import shutil
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from framework.artifacts import (
    calculate_file_sha256,
    copy_artifact_to_result,
    copy_material_directory_to_result,
    copy_material_to_result,
    write_material_inventory,
)
from framework.generated_state import (
    build_identity,
    detect_execution_identity,
    key_tuple_fingerprint,
    preflight_generated_state,
    record_generated_state_success,
)
from framework.signing_audit import append_signing_usage_event
from framework.fingerprint import (
    FingerprintInputError,
    calculate_existing_inputs_fingerprint,
    default_wolfboot_fingerprint_inputs,
)

# wolfBoot keygen exports concatenated raw private/public keys (ML-DSA-44/65/87).
ML_DSA_TUPLE_PARAMETERS = {"mldsa44": (2, 3872), "mldsa65": (3, 5984), "mldsa87": (5, 7488)}

MISSING_SOURCE_RETURN_CODE = 20
WOLFBOOT_BUILD_ARTIFACT_MISSING_RETURN_CODE = 21
PROFILE_ERROR_RETURN_CODE = 22
WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE = 23
WOLFBOOT_BINARY_CONVERSION_FAILED_RETURN_CODE = 24
DEFAULT_WOLFBOOT_RESULTS_SUBDIR = "wolfboot-builds"
DEFAULT_WOLFBOOT_LOG_NAME = "wolfboot_build.log"
MINGW_KEYTOOLS_STDIO_DEFINE = "-D__USE_MINGW_ANSI_STDIO=1"
KEYTOOLS_MAKEFILE_RELATIVE_PATH = Path("tools/keytools/Makefile")
STM32L4_HAL_CONF_RELATIVE_PATH = Path("hal/stm32l4xx_hal_conf.h")
STM32L4_HAL_SOURCE_RELATIVE_PATH = Path("hal/stm32l4.c")
WOLFBOOT_IMAGE_SOURCE_RELATIVE_PATH = Path("src/image.c")
WOLFBOOT_STM32L4_HAL_SOURCE_RELATIVE_PATH = Path("hal/stm32l4.c")
DEFAULT_WOLFBOOT_PRIVATE_KEY_RELATIVE_PATH = Path("wolfboot_signing_private_key.der")
WOLFBOOT_GENERATED_SIGNING_ARTIFACT_RELATIVE_PATHS = (
    Path("src/keystore.c"),
    DEFAULT_WOLFBOOT_PRIVATE_KEY_RELATIVE_PATH,
    Path("wolfboot_signing_public_key.der"),
    Path("wolfboot_signing_private_key.pem"),
    Path("wolfboot_signing_public_key.pem"),
)
STM32L4_HAL_CONF_PWR_MODULE_DEFINE = "#define HAL_PWR_MODULE_ENABLED"
WOLFBOOT_HOST_TOOL_OUTPUT_PATTERNS = (
    "tools/bin-assemble/*.o",
    "tools/bin-assemble/*.d",
    "tools/bin-assemble/bin-assemble",
    "tools/bin-assemble/bin-assemble.exe",
    "tools/keytools/*.o",
    "tools/keytools/*.d",
    "tools/keytools/keygen",
    "tools/keytools/keygen.exe",
    "tools/keytools/sign",
    "tools/keytools/sign.exe",
)
WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS = (
    # Objects from a previous single-bank profile must not survive a switch
    # to dual-bank OTA (or vice versa): wolfBoot's Makefile does not track
    # changes to the preprocessor configuration used to build these objects.
    "src/**/*.o",
    "src/**/*.d",
    "hal/**/*.o",
    "hal/**/*.d",
    "lib/wolfssl/**/*.o",
    "lib/wolfssl/**/*.d",
)


@dataclass(frozen=True)
class WolfBootCommandExecution:
    """Captured output from one wolfBoot build command invocation."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class WolfBootBuildResult:
    """Captured result from a configured wolfBoot build profile."""

    return_code: int
    duration_seconds: float
    profile_id: str
    result_dir: Path
    log_path: Path
    command: list[str]
    working_directory: Path
    source_dir: Path
    output_dir: Path
    artifact_path: Path
    artifact_exists: bool
    config_template_path: Path | None
    generated_config_path: Path | None
    config_applied: bool
    keytools_mingw_stdio_patch_enabled: bool
    keytools_mingw_stdio_patch_applied: bool
    keytools_makefile_path: Path | None
    stm32l4_hal_conf_pwr_patch_enabled: bool
    stm32l4_hal_conf_pwr_patch_applied: bool
    stm32l4_hal_conf_path: Path | None
    boot_timing_instrumentation_patch_enabled: bool
    boot_timing_instrumentation_patch_applied: bool
    boot_timing_image_path: Path | None
    boot_timing_hal_path: Path | None
    artifact_sha256: str | None
    retained_artifact_path: Path | None
    signing_key_path: Path | None
    wolfboot_private_key_path: Path | None
    signing_key_sha256: str | None
    wolfboot_private_key_sha256: str | None
    key_consistency_status: str
    key_consistency_message: str | None
    execution: WolfBootCommandExecution | None
    failure_reason: str | None = None


WolfBootRunner = Callable[[list[str], Path], WolfBootCommandExecution]


class WolfBootBuildProfileError(ValueError):
    """Raised when a wolfBoot build profile is incomplete or invalid."""


def _safe_id_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_.-")
    if not safe:
        raise WolfBootBuildProfileError("wolfBoot build profile id must contain at least one safe character")
    return safe


def _required(profile: dict[str, Any], dotted_path: str) -> Any:
    current: Any = profile
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise WolfBootBuildProfileError(
                f"wolfBoot build profile missing required field: {dotted_path}"
            )
        current = current[part]
    if current is None or current == "":
        raise WolfBootBuildProfileError(
            f"wolfBoot build profile has empty required field: {dotted_path}"
        )
    return current


def validate_wolfboot_build_profile(profile: dict[str, Any]) -> None:
    """Validate the minimum schema for a wolfBoot build profile."""

    required_fields = [
        "id",
        "description",
        "source_dir",
        "output_dir",
        "artifact",
        "signature_algorithm",
        "target",
        "build.command",
    ]

    for field in required_fields:
        _required(profile, field)

    algorithm = str(_required(profile, "signature_algorithm"))
    if algorithm not in {"integrity_sha256", "ecdsa_p256", "ed25519", "rsa2048", "ecc384", "ecc521", "ed448", "rsa3072", "rsa4096", "mldsa44", "mldsa65", "mldsa87"}:
        raise WolfBootBuildProfileError(
            "wolfBoot build profile signature_algorithm must be integrity_sha256, ecdsa_p256, ed25519, rsa2048, ecc384, ecc521, ed448, rsa3072, rsa4096, mldsa44, mldsa65, or mldsa87"
        )


def _requires_signing_material(profile: dict[str, Any]) -> bool:
    """Return whether the selected wolfBoot profile requires signing keys.

    The integrity-only baseline uses ``SIGN=NONE`` and embeds no verification
    key, so it must not enter persistent-tuple, key-generation, key-sync, or
    private-material retention paths.
    """

    return str(profile.get("signature_algorithm", "")) != "integrity_sha256"


def construct_wolfboot_build_command(profile: dict[str, Any]) -> list[str]:
    """Construct the configured wolfBoot build command.

    The profile stores the command and optional argument string as plain scalar
    values so the current small YAML parser can load it. The command is split
    with ``shlex.split``; no shell is used.
    """

    validate_wolfboot_build_profile(profile)
    build_config = profile.get("build", {})
    if not isinstance(build_config, dict):
        raise WolfBootBuildProfileError("wolfBoot build profile build field must be a mapping")

    command = shlex.split(str(build_config["command"]))
    args = shlex.split(str(build_config.get("args", "")))

    if not command:
        raise WolfBootBuildProfileError("wolfBoot build profile build.command produced an empty command")

    return command + args


def _optional_profile_path(profile: dict[str, Any], dotted_path: str) -> str | None:
    current: Any = profile
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    if current is None or current == "":
        return None
    return str(current)


def _optional_profile_bool(profile: dict[str, Any], dotted_path: str) -> bool:
    current: Any = profile
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current is True or str(current).strip().lower() in {"true", "yes", "1", "on"}


def _temporarily_patch_keytools_makefile(
    *,
    profile: dict[str, Any],
    source_dir: Path,
) -> tuple[Path | None, bool, str | None]:
    """Apply a temporary MinGW stdio compatibility define to host keytools.

    wolfBoot's host signing/key-generation tools are built by a nested
    ``tools/keytools`` makefile. On the project's Windows/MSYS toolchain, MinGW
    can reject C99 ``%j`` printf format checking unless
    ``__USE_MINGW_ANSI_STDIO`` is defined for those host objects. This patch is
    applied only while the configured wolfBoot build command runs and is then
    restored, so the wolfBoot submodule working tree is not left dirty.
    """

    if not _optional_profile_bool(profile, "build.mingw_keytools_ansi_stdio_patch"):
        return None, False, None

    makefile_path = source_dir / KEYTOOLS_MAKEFILE_RELATIVE_PATH
    if not makefile_path.is_file():
        raise WolfBootBuildProfileError(
            f"wolfBoot keytools Makefile not found for MinGW stdio patch: {makefile_path}"
        )

    original_text = makefile_path.read_text(encoding="utf-8")
    if MINGW_KEYTOOLS_STDIO_DEFINE in original_text:
        return makefile_path, True, None

    cflags_pattern = re.compile(r"^(CFLAGS\s*=\s*-Wall\s+-Wextra\s+-Werror)\s*$", re.MULTILINE)
    replacement = rf"\1\nCFLAGS += {MINGW_KEYTOOLS_STDIO_DEFINE}"
    patched_text, substitutions = cflags_pattern.subn(replacement, original_text, count=1)

    if substitutions != 1:
        raise WolfBootBuildProfileError(
            "Could not locate the expected keytools CFLAGS line for MinGW stdio patch"
        )

    makefile_path.write_text(patched_text, encoding="utf-8")
    return makefile_path, True, original_text



def _temporarily_patch_stm32l4_hal_conf(
    *,
    profile: dict[str, Any],
    source_dir: Path,
) -> tuple[Path | None, bool, str | None]:
    """Temporarily enable PWR/PWREx includes in wolfBoot's STM32L4 HAL config.

    Upstream wolfBoot's STM32L4 HAL config enables flash and RCC modules but not
    PWR. The STM32L4 flash extension source uses PWREx symbols on STM32L4R5, so
    the project-local target adaptation temporarily adds the PWR module define
    and matching PWR/PWREx includes while the build command runs. The original
    file is restored afterward so the wolfBoot submodule is not intentionally
    left dirty.
    """

    if not _optional_profile_bool(profile, "build.stm32l4_hal_conf_pwr_patch"):
        return None, False, None

    hal_conf_path = source_dir / STM32L4_HAL_CONF_RELATIVE_PATH
    if not hal_conf_path.is_file():
        raise WolfBootBuildProfileError(
            f"wolfBoot STM32L4 HAL config not found for PWR patch: {hal_conf_path}"
        )

    original_text = hal_conf_path.read_text(encoding="utf-8")
    has_define = STM32L4_HAL_CONF_PWR_MODULE_DEFINE in original_text
    has_pwr_include = '#include "stm32l4xx_hal_pwr.h"' in original_text
    has_pwr_ex_include = '#include "stm32l4xx_hal_pwr_ex.h"' in original_text
    if has_define and has_pwr_include and has_pwr_ex_include:
        return hal_conf_path, True, None

    patched_text = original_text

    if not has_define:
        if "#define HAL_RCC_MODULE_ENABLED" not in patched_text:
            raise WolfBootBuildProfileError(
                "Could not locate HAL_RCC_MODULE_ENABLED in wolfBoot STM32L4 HAL config"
            )
        patched_text = patched_text.replace(
            "#define HAL_RCC_MODULE_ENABLED",
            "#define HAL_RCC_MODULE_ENABLED\n#define HAL_PWR_MODULE_ENABLED",
            1,
        )

    if not has_pwr_include or not has_pwr_ex_include:
        rcc_include_block = (
            "#if defined(HAL_RCC_MODULE_ENABLED)\n"
            '#include "stm32l4xx_hal_rcc.h"\n'
            "#endif"
        )
        pwr_include_block = (
            "#if defined(HAL_PWR_MODULE_ENABLED)\n"
            '#include "stm32l4xx_hal_pwr.h"\n'
            '#include "stm32l4xx_hal_pwr_ex.h"\n'
            "#endif"
        )
        if rcc_include_block in patched_text:
            patched_text = patched_text.replace(
                rcc_include_block,
                f"{rcc_include_block}\n{pwr_include_block}",
                1,
            )
        elif "#define assert_param(expr)" in patched_text:
            patched_text = patched_text.replace(
                "#define assert_param(expr)",
                f"{pwr_include_block}\n#define assert_param(expr)",
                1,
            )
        else:
            raise WolfBootBuildProfileError(
                "Could not locate a safe insertion point for wolfBoot STM32L4 PWR includes"
            )

    hal_conf_path.write_text(patched_text, encoding="utf-8")
    return hal_conf_path, True, original_text



def _temporarily_patch_boot_timing_instrumentation(
    *,
    profile: dict[str, Any],
    source_dir: Path,
) -> tuple[Path | None, Path | None, bool, str | None, str | None]:
    """Temporarily instrument wolfBoot timing and reset-origin handoff.

    The patch keeps DWT cycle attribution for authenticity verification and
    adds a reset-origin record established in ``hal_init()``.  A 1 MHz LPTIM2
    bridge clocked directly from HSI16 spans the final wolfBoot handoff and the
    application clock transition; the application consumes that bridge before
    starting its dedicated 32-bit TIM2 timebase.  Both wolfBoot sources are
    restored after the build.
    """

    if not _optional_profile_bool(profile, "build.boot_timing_instrumentation_patch"):
        if _optional_profile_bool(profile, "build.runtime_stack_high_water_instrumentation"):
            raise WolfBootBuildProfileError("stack profiling requires the existing boot timing/mailbox patch")
        return None, None, False, None, None

    image_path = source_dir / WOLFBOOT_IMAGE_SOURCE_RELATIVE_PATH
    hal_path = source_dir / WOLFBOOT_STM32L4_HAL_SOURCE_RELATIVE_PATH
    if not image_path.is_file():
        raise WolfBootBuildProfileError(
            f"wolfBoot image source not found for boot timing patch: {image_path}"
        )
    if not hal_path.is_file():
        raise WolfBootBuildProfileError(
            f"wolfBoot STM32L4 HAL source not found for boot timing patch: {hal_path}"
        )

    # A small, fixed on-device identity avoids key parsing or hashing in wolfBoot.
    algorithm_ids = {
        "integrity_sha256": 1, "ecdsa_p256": 2, "ed25519": 3,
        "rsa2048": 4, "ecc384": 5, "ecc521": 6,
        "ed448": 7, "rsa3072": 8, "rsa4096": 9,
        "mldsa44": 10, "mldsa65": 11, "mldsa87": 12,
    }
    algorithm_name = str(_required(profile, "signature_algorithm"))
    algorithm_id = algorithm_ids[algorithm_name]
    # RSA modulus / ECDSA curve size are parameters, NOT encoded key lengths.
    parameter_bits = {
        "ecdsa_p256": 256, "ecc384": 384, "ecc521": 521,
        "rsa2048": 2048, "rsa3072": 3072, "rsa4096": 4096,
    }.get(algorithm_name, 0)
    # Profile-specified signature capacity is not necessarily actual signature length.
    declared_signature_size = profile.get("signature_size_bytes")
    if declared_signature_size is None:
        declared_signature_size = 0
    if not isinstance(declared_signature_size, int) or not 0 <= declared_signature_size <= 65535:
        raise WolfBootBuildProfileError("signature_size_bytes must be a nonnegative integer <= 65535")
    stack_profile = _optional_profile_bool(profile, "build.runtime_stack_high_water_instrumentation")
    original_image_text = image_path.read_text(encoding="utf-8")
    original_hal_text = hal_path.read_text(encoding="utf-8")
    image_marker = "PQC_BOOT_TIMING_WRAPPER_V3"
    hal_marker = "PQC_BOOT_RESET_ORIGIN_V3"

    patched_image_text = original_image_text
    patched_hal_text = original_hal_text
    image_original_to_restore: str | None = original_image_text
    hal_original_to_restore: str | None = original_hal_text

    if image_marker not in patched_image_text:
        integrity_signature = "int wolfBoot_verify_integrity(struct wolfBoot_image *img)\n{"
        if patched_image_text.count(integrity_signature) != 1:
            raise WolfBootBuildProfileError("Could not identify unique wolfBoot integrity verification implementation")
        patched_image_text = patched_image_text.replace(
            integrity_signature,
            "#if defined(WOLFBOOT_PQC_BOOT_TIMING)\n"
            "static int wolfBoot_verify_integrity_impl(struct wolfBoot_image *img)\n"
            "#else\nint wolfBoot_verify_integrity(struct wolfBoot_image *img)\n#endif\n{",
            1,
        )
        integrity_end = "#ifdef WOLFBOOT_ELF_FLASH_SCATTER"
        integrity_wrapper = r'''#if defined(WOLFBOOT_PQC_BOOT_TIMING)
/* PQC_BOOT_INTEGRITY_WRAPPER_V4: excludes mailbox writes and reporting. */
void pqc_boot_timing_integrity_begin(void);
void pqc_boot_timing_image_start(uint32_t start_cycles, struct wolfBoot_image *img);
void pqc_boot_timing_integrity_finish(uint32_t elapsed_cycles, int result, struct wolfBoot_image *img);
void pqc_boot_timing_image_finish(uint32_t end_cycles, int result, struct wolfBoot_image *img);
uint32_t pqc_boot_timing_diag_integrity_cycles(void);
uint32_t pqc_boot_timing_diag_integrity_valid(void);
uint32_t pqc_boot_timing_diag_authenticity_cycles(void);
uint32_t pqc_boot_timing_diag_authenticity_valid(void);
int wolfBoot_verify_integrity(struct wolfBoot_image *img)
{
    /* Invalidate any earlier candidate/recovery attempt before taking the DWT start read. */
    pqc_boot_timing_integrity_begin();
    uint32_t start_cycles = *(volatile uint32_t *)0xE0001004UL;
    pqc_boot_timing_image_start(start_cycles, img);
    int ret = wolfBoot_verify_integrity_impl(img);
    uint32_t end_cycles = *(volatile uint32_t *)0xE0001004UL;
    pqc_boot_timing_integrity_finish(end_cycles - start_cycles, ret, img);
#if defined(WOLFBOOT_NO_SIGN)
    pqc_boot_timing_image_finish(end_cycles, ret, img);
#endif
    return ret;
}
#endif
'''
        if integrity_end not in patched_image_text:
            raise WolfBootBuildProfileError("Could not locate integrity function end marker")
        patched_image_text = patched_image_text.replace(integrity_end, integrity_wrapper + "\n" + integrity_end, 1)
        signature = "#else\nint wolfBoot_verify_authenticity(struct wolfBoot_image *img)\n{"
        replacement = (
            "#else\n"
            "#if defined(WOLFBOOT_PQC_BOOT_TIMING)\n"
            "static int wolfBoot_verify_authenticity_impl(struct wolfBoot_image *img)\n"
            "#else\n"
            "int wolfBoot_verify_authenticity(struct wolfBoot_image *img)\n"
            "#endif\n"
            "{"
        )
        if signature not in patched_image_text:
            raise WolfBootBuildProfileError(
                "Could not locate wolfBoot_verify_authenticity() for boot timing patch"
            )
        patched_image_text = patched_image_text.replace(signature, replacement, 1)

        wrapper_marker = "#endif\n\n/**\n * @brief Peek at the content of the image at a specific offset."
        wrapper = r'''
#if defined(WOLFBOOT_PQC_BOOT_TIMING)
/* PQC_BOOT_TIMING_WRAPPER_V3 */
void pqc_boot_timing_verification_start(uint32_t *start_cycles);
void pqc_boot_timing_verification_finish(uint32_t elapsed_cycles, int verification_result, struct wolfBoot_image *img);

int wolfBoot_verify_authenticity(struct wolfBoot_image *img)
{
    uint32_t start_cycles;
    int ret;
    pqc_boot_timing_verification_start(&start_cycles);
    ret = wolfBoot_verify_authenticity_impl(img);
    uint32_t end_cycles = *(volatile uint32_t *)0xE0001004UL;
    pqc_boot_timing_verification_finish(end_cycles - start_cycles, ret, img);
    pqc_boot_timing_image_finish(end_cycles, ret, img);
    return ret;
}
#endif
'''
        if wrapper_marker not in patched_image_text:
            raise WolfBootBuildProfileError(
                "Could not locate safe insertion point after wolfBoot_verify_authenticity()"
            )
        patched_image_text = patched_image_text.replace(
            wrapper_marker, f"{wrapper}\n{wrapper_marker}", 1
        )
    else:
        image_original_to_restore = None

    if hal_marker not in patched_hal_text:
        helper_anchor = '#define DMB() asm volatile ("dmb")\n'
        helper = r'''

#if defined(WOLFBOOT_PQC_BOOT_TIMING)
/* PQC_BOOT_RESET_ORIGIN_V3 */
#ifndef WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR
#define WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR 0x10000000UL
#endif
#define PQC_BOOT_TIMING_MAILBOX_MAGIC 0x50514354UL
#define PQC_BOOT_TIMING_MAILBOX_VERSION 8UL
#define PQC_BOOT_STACK_UNAVAILABLE 0xFFFFFFFFUL
#define PQC_BOOT_RESET_ORIGIN_KIND_WOLFBOOT_ENTRY 1UL
#define PQC_BOOT_HANDOFF_BRIDGE_HZ 1000000UL
#define PQC_BOOT_HANDOFF_BRIDGE_BITS 16UL
#define PQC_BOOT_HSI_HZ 16000000UL
#define PQC_BOOT_MSI_HZ 4000000UL
#define PQC_BOOT_HSE_HZ 0UL
#define PQC_BOOT_DEMCR (*(volatile uint32_t *)0xE000EDFCUL)
#define PQC_BOOT_DWT_CTRL (*(volatile uint32_t *)0xE0001000UL)
#define PQC_BOOT_DWT_CYCCNT (*(volatile uint32_t *)0xE0001004UL)
#define PQC_BOOT_DEMCR_TRCENA (1UL << 24)
#define PQC_BOOT_DWT_CYCCNTENA (1UL << 0)

struct pqc_boot_timing_mailbox {
    uint32_t magic;
    uint32_t version;
    uint32_t elapsed_cycles;
    uint32_t verification_result;
    uint32_t max_stack_used_bytes;
    uint32_t sysclk_hz;
    uint32_t hclk_hz;
    uint32_t pclk1_hz;
    uint32_t pclk2_hz;
    uint32_t reset_origin_to_handoff_us_low;
    uint32_t reset_origin_to_handoff_us_high;
    uint32_t reset_origin_kind;
    uint32_t handoff_bridge_counter_hz;
    uint32_t handoff_bridge_counter_bits;
    uint32_t handoff_bridge_status;
    uint32_t integrity_cycles;
    int32_t integrity_result;
    uint32_t integrity_valid;
    uint32_t authenticity_cycles;
    int32_t authenticity_result;
    uint32_t authenticity_valid;
    uint32_t signature_algorithm_id;
    uint32_t signature_parameter_bits;
    uint32_t declared_signature_capacity_bytes;
    /* SHA-256 image-content digest validated by wolfBoot; not the full .bin hash. */
    uint32_t verified_image_digest_valid;
    uint32_t verified_image_part;
    uint32_t verified_image_fw_size;
    uint8_t verified_image_sha256[32];
    /* Appended-only v7: independent enclosing DWT interval and selected image. */
    uint32_t image_verification_cycles;
    uint32_t image_verification_valid;
    uint32_t selected_image_valid;
    uint32_t selected_image_part;
    uint32_t selected_image_fw_size;
    /* v8: default-off stack profiling; 1=measured, 2=unavailable. */
    uint32_t stack_profiling_enabled;
    uint32_t stack_measurement_status;
    uint32_t stack_watermark_capacity_bytes;
};
/* The OTA event mailbox starts at RAM2+0x100: never overlap it. */
typedef char pqc_boot_timing_mailbox_fits_ota_events[
    (sizeof(struct pqc_boot_timing_mailbox) <= 0x100U) ? 1 : -1];

static uint64_t pqc_boot_reset_prefix_us;
static uint32_t pqc_boot_stable_hclk_hz;
static uint32_t pqc_boot_reset_origin_valid = 1U;
static uint32_t pqc_boot_image_start_cycles;
static uint32_t pqc_boot_image_start_part;
static uint32_t pqc_boot_image_start_size;
static uint32_t pqc_boot_image_started;
#if defined(PQC_BOOT_STACK_PROFILING)
/* Stack starts at END_STACK, grows down into RAM below the live MSP. */
extern uint32_t _end_bss;
extern uint32_t END_STACK;
static volatile uint32_t *pqc_boot_stack_low;
static volatile uint32_t *pqc_boot_stack_high;
#define PQC_BOOT_STACK_PATTERN 0xA55A3CC3UL
#define PQC_BOOT_STACK_GUARD_BYTES 128UL
#endif

static uint32_t pqc_boot_decode_ahb_divider(uint32_t hpre)
{
    static const uint16_t dividers[16] = {1U,1U,1U,1U,1U,1U,1U,1U,2U,4U,8U,16U,64U,128U,256U,512U};
    return dividers[hpre & 0xFU];
}

static uint32_t pqc_boot_decode_apb_divider(uint32_t ppre)
{
    static const uint8_t dividers[8] = {1U,1U,1U,1U,2U,4U,8U,16U};
    return dividers[ppre & 0x7U];
}

static uint32_t pqc_boot_pll_source_hz(uint32_t pllcfgr)
{
    switch (pllcfgr & RCC_PLLCFGR_PLLSRC) {
        case RCC_PLLSOURCE_MSI: return PQC_BOOT_MSI_HZ;
        case RCC_PLLSOURCE_HSI: return PQC_BOOT_HSI_HZ;
        default: return PQC_BOOT_HSE_HZ;
    }
}

static uint32_t pqc_boot_reported_sysclk_hz(void)
{
    uint32_t cfgr = RCC->CFGR;
    uint32_t sws = cfgr & RCC_CFGR_SWS;
    if (sws == RCC_CFGR_SWS_HSI) return PQC_BOOT_HSI_HZ;
    if (sws == RCC_CFGR_SWS_MSI) return PQC_BOOT_MSI_HZ;
    if (sws == RCC_CFGR_SWS_HSE) return PQC_BOOT_HSE_HZ;
    if (sws == RCC_CFGR_SWS_PLL) {
        uint32_t pll = RCC->PLLCFGR;
        uint32_t source_hz = pqc_boot_pll_source_hz(pll);
        uint32_t m = ((pll & RCC_PLLCFGR_PLLM) >> RCC_PLLCFGR_PLLM_Pos) + 1U;
        uint32_t n = (pll & RCC_PLLCFGR_PLLN) >> RCC_PLLCFGR_PLLN_Pos;
        uint32_t r = ((((pll & RCC_PLLCFGR_PLLR) >> RCC_PLLCFGR_PLLR_Pos) + 1U) * 2U);
        if ((source_hz == 0U) || (m == 0U) || (r == 0U)) return 0U;
        return (uint32_t)((((uint64_t)source_hz / m) * n) / r);
    }
    return 0U;
}

static void pqc_boot_reported_clocks(uint32_t *sysclk_hz, uint32_t *hclk_hz, uint32_t *pclk1_hz, uint32_t *pclk2_hz)
{
    uint32_t cfgr = RCC->CFGR;
    uint32_t sysclk = pqc_boot_reported_sysclk_hz();
    uint32_t hclk = sysclk / pqc_boot_decode_ahb_divider((cfgr & RCC_CFGR_HPRE) >> RCC_CFGR_HPRE_Pos);
    *sysclk_hz = sysclk;
    *hclk_hz = hclk;
    *pclk1_hz = hclk / pqc_boot_decode_apb_divider((cfgr & RCC_CFGR_PPRE1) >> RCC_CFGR_PPRE1_Pos);
    *pclk2_hz = hclk / pqc_boot_decode_apb_divider((cfgr & RCC_CFGR_PPRE2) >> RCC_CFGR_PPRE2_Pos);
}

static uint64_t pqc_boot_cycles_to_us(uint32_t cycles, uint32_t hclk_hz)
{
    if (hclk_hz == 0U) return 0U;
    return (((uint64_t)cycles * 1000000ULL) + ((uint64_t)hclk_hz / 2ULL)) / (uint64_t)hclk_hz;
}

static void pqc_boot_dwt_reset(void)
{
    PQC_BOOT_DEMCR |= PQC_BOOT_DEMCR_TRCENA;
    PQC_BOOT_DWT_CTRL |= PQC_BOOT_DWT_CYCCNTENA;
    PQC_BOOT_DWT_CYCCNT = 0U;
}

static uint16_t pqc_boot_bridge_read(void)
{
    uint16_t first, second;
    do {
        first = (uint16_t)LPTIM2->CNT;
        second = (uint16_t)LPTIM2->CNT;
    } while (first != second);
    return second;
}

static int pqc_boot_bridge_start(uint32_t *counter_start_cycle)
{
    RCC->CR |= RCC_CR_HSION;
    while ((RCC->CR & RCC_CR_HSIRDY) == 0U) {}
    __HAL_RCC_LPTIM2_CONFIG(RCC_LPTIM2CLKSOURCE_HSI);
    __HAL_RCC_LPTIM2_CLK_ENABLE();
    LPTIM2->CR = 0U;
    LPTIM2->CFGR = (LPTIM2->CFGR & ~LPTIM_CFGR_PRESC) | LPTIM_CFGR_PRESC_2;
    LPTIM2->ICR = LPTIM_ICR_ARRMCF | LPTIM_ICR_ARROKCF;
    LPTIM2->CR = LPTIM_CR_ENABLE;
    LPTIM2->ARR = 0xFFFFU;
    while ((LPTIM2->ISR & LPTIM_ISR_ARROK) == 0U) {}
    LPTIM2->ICR = LPTIM_ICR_ARROKCF | LPTIM_ICR_ARRMCF;
    if (counter_start_cycle != NULL) *counter_start_cycle = PQC_BOOT_DWT_CYCCNT;
    LPTIM2->CR |= LPTIM_CR_CNTSTRT;
    return 0;
}

static uint32_t pqc_boot_bridge_elapsed_us(void)
{
    if ((LPTIM2->ISR & LPTIM_ISR_ARRM) != 0U) return 0xFFFFFFFFUL;
    return (uint32_t)pqc_boot_bridge_read();
}

#if defined(PQC_BOOT_STACK_PROFILING)
/* Runs before each integrity verification attempt. Excludes 128 bytes below
 * sampled MSP for the initializer and its callers. This is a conservative
 * observable boundary, not evidence of peak use within the exclusion.
 * The lower 128 bytes above BSS remain a collision sentinel. */
static void pqc_boot_stack_initialize(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    uintptr_t msp;
    uintptr_t low = ((uintptr_t)&_end_bss + 131U) & ~(uintptr_t)3U;
    uintptr_t high;
    volatile uint32_t *p;
    __asm__ volatile("mrs %0, msp" : "=r" (msp));
    pqc_boot_stack_low = NULL;
    pqc_boot_stack_high = NULL;
    mailbox->stack_profiling_enabled = 1U;
    mailbox->stack_measurement_status = 2U;
    mailbox->max_stack_used_bytes = PQC_BOOT_STACK_UNAVAILABLE;
    mailbox->stack_watermark_capacity_bytes = 0U;
    if (msp <= PQC_BOOT_STACK_GUARD_BYTES) return;
    high = (msp - PQC_BOOT_STACK_GUARD_BYTES) & ~(uintptr_t)3U;
    if (low >= high || high > (uintptr_t)&END_STACK ||
        high - low < 512U) return;
    pqc_boot_stack_low = (volatile uint32_t *)low;
    pqc_boot_stack_high = (volatile uint32_t *)high;
    mailbox->stack_watermark_capacity_bytes = (uint32_t)(high - low);
    for (p = pqc_boot_stack_low; p < pqc_boot_stack_high; ++p)
        *p = PQC_BOOT_STACK_PATTERN;
    /* Distinguish an untouched paint from an initialization failure. */
    mailbox->stack_measurement_status = 3U;
}

/* Called only after the DWT end snapshot and mailbox timing writes. The
 * bottom sentinel must remain untouched. If no watermark word was consumed,
 * or the observed region is saturated, report unavailable instead of guessing. */
static void pqc_boot_stack_finish(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    volatile uint32_t *p;
    uintptr_t scan_msp;
    __asm__ volatile("mrs %0, msp" : "=r" (scan_msp));
    if (pqc_boot_stack_low == NULL || pqc_boot_stack_high == NULL) return;
    if (*pqc_boot_stack_low != PQC_BOOT_STACK_PATTERN) {
        mailbox->stack_measurement_status = 4U;
        return;
    }
    for (p = pqc_boot_stack_low; p < pqc_boot_stack_high; ++p) {
        if (*p != PQC_BOOT_STACK_PATTERN) {
            uint32_t bytes = (uint32_t)((uintptr_t)&END_STACK - (uintptr_t)p);
            /* Reject a shallow mark that could have been made by the
             * measurement function's own stack frame. A nonzero value is
             * retained only when the deepest write predates this scan. */
            if (p == pqc_boot_stack_low || bytes == 0U ||
                (uintptr_t)p + 32U >= scan_msp) {
                mailbox->stack_measurement_status = 5U;
                return;
            }
            mailbox->magic = 0U;
            mailbox->max_stack_used_bytes = bytes;
            mailbox->stack_measurement_status = 1U;
            mailbox->magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
            return;
        }
    }
}
#endif

static void pqc_boot_reset_origin_start(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    mailbox->magic = 0U;
    mailbox->integrity_cycles = 0U;
    mailbox->integrity_result = 0;
    mailbox->integrity_valid = 0U;
    mailbox->authenticity_cycles = 0U;
    mailbox->authenticity_result = 0;
    mailbox->authenticity_valid = 0U;
    mailbox->signature_algorithm_id = PQC_BOOT_SIGNATURE_ALGORITHM_ID;
    mailbox->signature_parameter_bits = PQC_BOOT_SIGNATURE_PARAMETER_BITS;
    mailbox->declared_signature_capacity_bytes = PQC_BOOT_DECLARED_SIGNATURE_CAPACITY_BYTES;
    mailbox->verified_image_digest_valid = 0U;
    mailbox->verified_image_part = 0U;
    mailbox->verified_image_fw_size = 0U;
    mailbox->image_verification_cycles = 0U;
    mailbox->image_verification_valid = 0U;
    mailbox->selected_image_valid = 0U;
    mailbox->selected_image_part = 0U;
    mailbox->selected_image_fw_size = 0U;
    mailbox->stack_profiling_enabled = 0U;
    mailbox->stack_measurement_status = 0U;
    mailbox->stack_watermark_capacity_bytes = 0U;
    mailbox->max_stack_used_bytes = PQC_BOOT_STACK_UNAVAILABLE;
    pqc_boot_image_started = 0U;
    { unsigned int i; for (i = 0U; i < 32U; ++i) mailbox->verified_image_sha256[i] = 0U; }
    uint32_t entry_hclk_hz;
    uint32_t start_cycles;
    uint32_t sysclk_hz, pclk1_hz, pclk2_hz;
    pqc_boot_reported_clocks(&sysclk_hz, &entry_hclk_hz, &pclk1_hz, &pclk2_hz);
    (void)sysclk_hz; (void)pclk1_hz; (void)pclk2_hz;
    pqc_boot_dwt_reset();
    start_cycles = PQC_BOOT_DWT_CYCCNT;
    {
        uint32_t bridge_start_cycle = start_cycles;
        (void)pqc_boot_bridge_start(&bridge_start_cycle);
        pqc_boot_reset_prefix_us = pqc_boot_cycles_to_us(
            bridge_start_cycle - start_cycles, entry_hclk_hz);
    }
}

static void pqc_boot_reset_origin_clock_ready(void)
{
    uint32_t bridge_us = pqc_boot_bridge_elapsed_us();
    uint32_t sysclk_hz, pclk1_hz, pclk2_hz;
    if (bridge_us != 0xFFFFFFFFUL) {
        pqc_boot_reset_prefix_us += bridge_us;
    } else {
        pqc_boot_reset_origin_valid = 0U;
    }
    pqc_boot_reported_clocks(&sysclk_hz, &pqc_boot_stable_hclk_hz, &pclk1_hz, &pclk2_hz);
    (void)sysclk_hz; (void)pclk1_hz; (void)pclk2_hz;
    pqc_boot_dwt_reset();
}

void pqc_boot_timing_integrity_begin(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    /* An integrity attempt may target a different image after a bank fallback,
     * emergency update, or candidate-manifest check. Do not carry its earlier
     * authenticity or digest evidence into the next attempt. This runs BEFORE
     * the measured integrity interval, not inside the DWT start/end reads. */
    mailbox->magic = 0U;
    mailbox->integrity_valid = 0U;
    mailbox->integrity_cycles = 0U;
    mailbox->integrity_result = 0;
    mailbox->authenticity_valid = 0U;
    mailbox->authenticity_cycles = 0U;
    mailbox->authenticity_result = 0;
    mailbox->elapsed_cycles = 0U;
    mailbox->verification_result = 0U;
    mailbox->verified_image_digest_valid = 0U;
    mailbox->verified_image_part = 0U;
    mailbox->verified_image_fw_size = 0U;
    mailbox->image_verification_valid = 0U;
    mailbox->image_verification_cycles = 0U;
    mailbox->selected_image_valid = 0U;
    mailbox->max_stack_used_bytes = PQC_BOOT_STACK_UNAVAILABLE;
    mailbox->stack_measurement_status = mailbox->stack_profiling_enabled ? 2U : 0U;
    pqc_boot_image_started = 0U;
#if defined(PQC_BOOT_STACK_PROFILING)
    pqc_boot_stack_initialize();
#endif
}

void pqc_boot_timing_image_start(uint32_t start_cycles, struct wolfBoot_image *img)
{
    if (img != NULL) {
        pqc_boot_image_start_cycles = start_cycles;
        pqc_boot_image_start_part = img->part;
        pqc_boot_image_start_size = img->fw_size;
        pqc_boot_image_started = 1U;
    }
}

void pqc_boot_timing_image_finish(uint32_t end_cycles, int result, struct wolfBoot_image *img)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    /* The enclosing interval starts at the integrity DWT read and finishes
     * at the authenticity DWT read (integrity read for SIGN=NONE). */
    if (pqc_boot_image_started != 0U && img != NULL && result == 0 &&
        img->part == pqc_boot_image_start_part &&
        img->fw_size == pqc_boot_image_start_size &&
        mailbox->integrity_valid == 1U && mailbox->integrity_result == 0 &&
        mailbox->verified_image_digest_valid == 1U &&
        (mailbox->authenticity_valid == 1U ||
         mailbox->signature_algorithm_id == 1U)) {
        uint32_t cycles = end_cycles - pqc_boot_image_start_cycles;
        if (cycles != 0U && mailbox->hclk_hz != 0U &&
            cycles <= mailbox->hclk_hz * 30U) {
            mailbox->magic = 0U;
            mailbox->image_verification_cycles = cycles;
            mailbox->image_verification_valid = 1U;
            mailbox->magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
        }
    }
#if defined(PQC_BOOT_STACK_PROFILING)
    if (mailbox->image_verification_valid == 1U && result == 0)
        pqc_boot_stack_finish();
#endif
    pqc_boot_image_started = 0U;
}

void pqc_boot_timing_verification_start(uint32_t *start_cycles)
{
    if (start_cycles != NULL) *start_cycles = PQC_BOOT_DWT_CYCCNT;
}

void pqc_boot_timing_verification_finish(uint32_t elapsed_cycles, int verification_result,
    struct wolfBoot_image *img)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    uint32_t sysclk_hz, hclk_hz, pclk1_hz, pclk2_hz;
    pqc_boot_reported_clocks(&sysclk_hz, &hclk_hz, &pclk1_hz, &pclk2_hz);
    mailbox->magic = 0U;
    mailbox->version = PQC_BOOT_TIMING_MAILBOX_VERSION;
    /* Match the authenticity operation to the image that passed the most
     * recent integrity check. SIGN=NONE has no signature measurement. */
    uint32_t same_image = 0U;
    if ((mailbox->integrity_valid != 0U) &&
        (mailbox->integrity_result == 0) &&
        (mailbox->verified_image_digest_valid == 1U) &&
        (img != NULL) && (img->sha_hash != NULL) &&
        (img->part == mailbox->verified_image_part) &&
        (img->fw_size == mailbox->verified_image_fw_size) &&
        (WOLFBOOT_SHA_DIGEST_SIZE == 32U)) {
        unsigned int i;
        same_image = 1U;
        for (i = 0U; i < 32U; ++i) {
            if (img->sha_hash[i] != mailbox->verified_image_sha256[i]) {
                same_image = 0U;
                break;
            }
        }
    }
    mailbox->authenticity_valid = 0U;
    mailbox->authenticity_cycles = 0U;
    mailbox->authenticity_result = 0;
#if !defined(WOLFBOOT_NO_SIGN)
    if (same_image != 0U && elapsed_cycles != 0U) {
        mailbox->authenticity_cycles = elapsed_cycles;
        mailbox->authenticity_result = verification_result;
        mailbox->authenticity_valid = 1U;
    }
#else
    (void)same_image;
#endif
    mailbox->elapsed_cycles = mailbox->authenticity_cycles;
    mailbox->verification_result = (uint32_t)verification_result;
    mailbox->sysclk_hz = sysclk_hz;
    mailbox->hclk_hz = hclk_hz;
    mailbox->pclk1_hz = pclk1_hz;
    mailbox->pclk2_hz = pclk2_hz;
    mailbox->reset_origin_to_handoff_us_low = 0U;
    mailbox->reset_origin_to_handoff_us_high = 0U;
    mailbox->reset_origin_kind = PQC_BOOT_RESET_ORIGIN_KIND_WOLFBOOT_ENTRY;
    mailbox->handoff_bridge_counter_hz = PQC_BOOT_HANDOFF_BRIDGE_HZ;
    mailbox->handoff_bridge_counter_bits = PQC_BOOT_HANDOFF_BRIDGE_BITS;
    mailbox->handoff_bridge_status = 0U;
    mailbox->magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
}

void pqc_boot_timing_integrity_finish(uint32_t elapsed_cycles, int result, struct wolfBoot_image *img)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    uint32_t sysclk_hz, hclk_hz, pclk1_hz, pclk2_hz;
    pqc_boot_reported_clocks(&sysclk_hz, &hclk_hz, &pclk1_hz, &pclk2_hz);
    mailbox->magic = 0U;
    mailbox->version = PQC_BOOT_TIMING_MAILBOX_VERSION;
    mailbox->integrity_cycles = elapsed_cycles;
    mailbox->integrity_result = result;
    mailbox->integrity_valid = (elapsed_cycles != 0U);
    /* The DWT end snapshot was taken in image.c before this copy. */
    mailbox->verified_image_digest_valid = 0U;
    mailbox->verified_image_part = 0U;
    mailbox->verified_image_fw_size = 0U;
    if ((result == 0) && (img != NULL) && (img->sha_hash != NULL) &&
        (WOLFBOOT_SHA_DIGEST_SIZE == 32U)) {
        unsigned int i;
        mailbox->verified_image_part = img->part;
        mailbox->verified_image_fw_size = img->fw_size;
        for (i = 0U; i < 32U; ++i)
            mailbox->verified_image_sha256[i] = img->sha_hash[i];
        mailbox->verified_image_digest_valid = 1U;
    }
    mailbox->sysclk_hz = sysclk_hz;
    mailbox->hclk_hz = hclk_hz;
    mailbox->pclk1_hz = pclk1_hz;
    mailbox->pclk2_hz = pclk2_hz;
    mailbox->magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
}

uint32_t pqc_boot_timing_diag_integrity_cycles(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    return mailbox->integrity_cycles;
}

uint32_t pqc_boot_timing_diag_integrity_valid(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    return mailbox->integrity_valid;
}

uint32_t pqc_boot_timing_diag_authenticity_cycles(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    return mailbox->authenticity_cycles;
}

uint32_t pqc_boot_timing_diag_authenticity_valid(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    return mailbox->authenticity_valid;
}

void pqc_boot_timing_select_image(struct wolfBoot_image *img)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    mailbox->magic = 0U;
    mailbox->selected_image_valid = 0U;
    if (img != NULL && mailbox->verified_image_digest_valid == 1U &&
        mailbox->integrity_valid == 1U && mailbox->integrity_result == 0 &&
        mailbox->image_verification_valid == 1U &&
        (mailbox->signature_algorithm_id == 1U ||
         (mailbox->authenticity_valid == 1U && mailbox->authenticity_result == 0)) &&
        img->part == mailbox->verified_image_part &&
        img->fw_size == mailbox->verified_image_fw_size &&
        img->sha_hash != NULL && WOLFBOOT_SHA_DIGEST_SIZE == 32U) {
        unsigned int i;
        uint32_t match = 1U;
        for (i = 0U; i < 32U; ++i) {
            if (img->sha_hash[i] != mailbox->verified_image_sha256[i]) match = 0U;
        }
        if (match != 0U) {
            mailbox->selected_image_part = img->part;
            mailbox->selected_image_fw_size = img->fw_size;
            mailbox->selected_image_valid = 1U;
        }
    }
    if (mailbox->selected_image_valid != 1U) {
        mailbox->max_stack_used_bytes = PQC_BOOT_STACK_UNAVAILABLE;
        mailbox->stack_measurement_status = mailbox->stack_profiling_enabled ? 2U : 0U;
    }
    mailbox->magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
}

static void pqc_boot_timing_prepare_handoff(void)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    uint32_t bridge_start_cycle = PQC_BOOT_DWT_CYCCNT;
    int bridge_status = pqc_boot_bridge_start(&bridge_start_cycle);
    uint64_t reset_to_bridge_us = pqc_boot_reset_prefix_us +
        pqc_boot_cycles_to_us(bridge_start_cycle, pqc_boot_stable_hclk_hz);
    mailbox->magic = 0U;
    mailbox->version = PQC_BOOT_TIMING_MAILBOX_VERSION;
    mailbox->reset_origin_to_handoff_us_low = (uint32_t)reset_to_bridge_us;
    mailbox->reset_origin_to_handoff_us_high = (uint32_t)(reset_to_bridge_us >> 32);
    mailbox->reset_origin_kind = PQC_BOOT_RESET_ORIGIN_KIND_WOLFBOOT_ENTRY;
    mailbox->handoff_bridge_counter_hz = PQC_BOOT_HANDOFF_BRIDGE_HZ;
    mailbox->handoff_bridge_counter_bits = PQC_BOOT_HANDOFF_BRIDGE_BITS;
    mailbox->handoff_bridge_status =
        ((pqc_boot_reset_origin_valid != 0U) && (bridge_status == 0)) ? 1U : 0U;
    mailbox->magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
}
#endif
'''
        if stack_profile:
            helper = "#define PQC_BOOT_STACK_PROFILING 1\n" + helper
        helper = (
            "#define PQC_BOOT_SIGNATURE_ALGORITHM_ID " + str(algorithm_id) + "UL\n"
            "#define PQC_BOOT_SIGNATURE_PARAMETER_BITS " + str(parameter_bits) + "UL\n"
            "#define PQC_BOOT_DECLARED_SIGNATURE_CAPACITY_BYTES " + str(declared_signature_size) + "UL\n"
            + helper
        )
        if helper_anchor not in patched_hal_text:
            raise WolfBootBuildProfileError(
                "Could not locate STM32L4 DMB helper for reset-origin timing patch"
            )
        patched_hal_text = patched_hal_text.replace(
            helper_anchor, helper_anchor + helper, 1
        )

        # Anchor only on the stable start of hal_init() and its clock setup.  The
        # body may legitimately contain optional target diagnostics after
        # clockconfig(0), so matching the complete function would make the
        # reset-origin patch unnecessarily dependent on unrelated features.
        hal_init_anchor = "void hal_init(void)\n{\n    clockconfig(0);"
        hal_init_instrumented = (
            "void hal_init(void)\n{\n"
            "#if defined(WOLFBOOT_PQC_BOOT_TIMING)\n"
            "    pqc_boot_reset_origin_start();\n"
            "#endif\n"
            "    clockconfig(0);\n"
            "#if defined(WOLFBOOT_PQC_BOOT_TIMING)\n"
            "    pqc_boot_reset_origin_clock_ready();\n"
            "#endif"
        )
        if patched_hal_text.count(hal_init_anchor) != 1:
            raise WolfBootBuildProfileError(
                "Could not locate unique wolfBoot STM32L4 hal_init() clock anchor for reset-origin patch"
            )
        patched_hal_text = patched_hal_text.replace(
            hal_init_anchor, hal_init_instrumented, 1
        )

        prepare_old = "void hal_prepare_boot(void)\n{"
        prepare_new = (
            "void hal_prepare_boot(void)\n{\n"
            "#if defined(WOLFBOOT_PQC_BOOT_TIMING)\n"
            "    pqc_boot_timing_prepare_handoff();\n"
            "#endif"
        )
        if prepare_old not in patched_hal_text:
            raise WolfBootBuildProfileError(
                "Could not locate wolfBoot STM32L4 hal_prepare_boot() for reset-origin patch"
            )
        patched_hal_text = patched_hal_text.replace(prepare_old, prepare_new, 1)
    else:
        hal_original_to_restore = None

    if patched_image_text != original_image_text:
        image_path.write_text(patched_image_text, encoding="utf-8")
    if patched_hal_text != original_hal_text:
        hal_path.write_text(patched_hal_text, encoding="utf-8")

    return (
        image_path,
        hal_path,
        True,
        image_original_to_restore,
        hal_original_to_restore,
    )


def _copy_project_local_config(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    source_dir: Path,
) -> tuple[Path | None, Path | None, bool]:
    """Materialise the complete resolved wolfBoot .config into the source tree."""

    config_template = _optional_profile_path(profile, "build.config_template")
    config_content = _optional_profile_path(profile, "build.config_content")
    generated_config = _optional_profile_path(profile, "build.generated_config")

    if config_template is None and config_content is None and generated_config is None:
        return None, None, False
    if generated_config is None or (config_template is None) == (config_content is None):
        raise WolfBootBuildProfileError(
            "wolfBoot build profile must pair build.generated_config with exactly one of "
            "build.config_template or build.config_content"
        )

    generated_path = repo_root / generated_config
    try:
        generated_path.relative_to(source_dir)
    except ValueError as exc:
        raise WolfBootBuildProfileError(
            "wolfBoot build.generated_config must be inside the configured source_dir"
        ) from exc
    generated_path.parent.mkdir(parents=True, exist_ok=True)

    if config_content is not None:
        generated_path.write_text(config_content, encoding="utf-8")
        return None, generated_path, True

    template_path = repo_root / str(config_template)
    if not template_path.is_file():
        raise WolfBootBuildProfileError(f"wolfBoot build config template not found: {template_path}")
    shutil.copyfile(template_path, generated_path)
    return template_path, generated_path, True


def _remove_wolfboot_host_tool_outputs(source_dir: Path) -> list[Path]:
    """Remove generated host and profile-dependent objects before a build.

    wolfBoot builds host utilities, bootloader/HAL objects, and target wolfCrypt
    objects inside one shared checkout. The object names do not encode the selected signing
    algorithm or preprocessor configuration. Reusing an object produced by a
    previous profile can therefore create incompatible symbol references, such
    as an ML-DSA SHA-3 object expecting ``BlockSha3`` while the current linked
    assembly objects were built under different settings.

    Only generated object, dependency, and host-tool executable files are
    removed. Source files, generated signing tuples, and persistent keys are
    not part of these patterns.
    """

    removed: list[Path] = []
    patterns = (
        *WOLFBOOT_HOST_TOOL_OUTPUT_PATTERNS,
        *WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS,
    )
    for pattern in patterns:
        for path in source_dir.glob(pattern):
            if not path.exists() or path.is_dir():
                continue
            path.unlink()
            removed.append(path)
    return removed


def _remove_wolfboot_generated_signing_artifacts(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    source_dir: Path,
) -> list[Path]:
    """Remove generated wolfBoot signing artifacts before each profile build.

    wolfBoot generates ``src/keystore.c`` and local signing-key material inside
    its source tree. The project reuses one wolfBoot checkout for several
    signing algorithms, so stale generated artifacts from a previous profile can
    make the next non-interactive build fail with a key-algorithm mismatch. Only
    files under the wolfBoot source directory are removed here; canonical
    project signing keys under ``secrets/`` are never deleted.
    """

    candidate_paths: set[Path] = {
        source_dir / relative_path
        for relative_path in WOLFBOOT_GENERATED_SIGNING_ARTIFACT_RELATIVE_PATHS
    }

    generated_keystore = _optional_profile_path(profile, "build.generated_keystore")
    if generated_keystore is not None:
        candidate_paths.add(repo_root / generated_keystore)

    wolfboot_private_key = _resolve_wolfboot_private_key_path(
        repo_root=repo_root,
        source_dir=source_dir,
        profile=profile,
    )
    if wolfboot_private_key is not None:
        candidate_paths.add(wolfboot_private_key)

    removed: list[Path] = []
    for path in sorted(candidate_paths):
        try:
            path.relative_to(source_dir)
        except ValueError:
            continue
        if not path.exists() or path.is_dir():
            continue
        path.unlink()
        removed.append(path)
    return removed


def _prepare_wolfboot_signing_artifacts(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    source_dir: Path,
    signing_key_path: Path | None,
    wolfboot_private_key_path: Path | None,
) -> tuple[list[Path], str | None]:
    """Prepare wolfBoot signing artifacts without breaking reusable key state.

    When no canonical key exists, generated wolfBoot signing artifacts are
    removed so wolfBoot can create a fresh key and matching keystore. When a
    canonical key already exists, the local private key and generated keystore
    must already form a reusable tuple. The wrapper cannot safely reconstruct a
    keystore from a private key alone, so missing or mismatched state is reported
    before invoking make.
    """

    if signing_key_path is None or not signing_key_path.is_file():
        return (
            _remove_wolfboot_generated_signing_artifacts(
                profile=profile,
                repo_root=repo_root,
                source_dir=source_dir,
            ),
            None,
        )

    generated_keystore = _optional_profile_path(profile, "build.generated_keystore")
    keystore_path = (
        repo_root / generated_keystore
        if generated_keystore is not None
        else source_dir / "src" / "keystore.c"
    )

    if wolfboot_private_key_path is None or not wolfboot_private_key_path.is_file():
        return [], (
            "The configured canonical signing key exists, but the matching "
            "wolfBoot private key is missing. The framework cannot safely "
            "reconstruct the generated keystore from the private key alone. "
            "Restore the matching wolfBoot key/keystore tuple or rotate the "
            "local benchmark key by backing up and removing the canonical key, "
            "then rerun build-wolfboot so wolfBoot generates a fresh tuple."
        )

    canonical_sha256 = calculate_file_sha256(signing_key_path)
    wolfboot_sha256 = calculate_file_sha256(wolfboot_private_key_path)
    if canonical_sha256 != wolfboot_sha256:
        return [], (
            "The configured canonical signing key and wolfBoot private key "
            "differ, so the existing generated keystore cannot be trusted. "
            "Restore the matching local key/keystore tuple or rotate the local "
            "benchmark key explicitly before rebuilding."
        )

    if not keystore_path.is_file():
        return [], (
            "The configured canonical signing key matches the wolfBoot private "
            "key, but the generated wolfBoot keystore is missing: "
            f"{keystore_path}. wolfBoot v2.9.0 cannot regenerate keystore.c "
            "from an existing private key alone. Restore the matching keystore "
            "or rotate the local benchmark key by backing up and removing the "
            "canonical key and wolfBoot-local key, then rerun build-wolfboot."
        )

    return [], None



def _signing_tuple_config(profile: dict[str, Any]) -> dict[str, Any] | None:
    build = profile.get("build")
    if not isinstance(build, dict):
        return None
    value = build.get("signing_tuple")
    return value if isinstance(value, dict) else None


def _signing_tuple_paths(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    source_dir: Path,
) -> dict[str, Path] | None:
    config = _signing_tuple_config(profile)
    if config is None:
        return None
    tuple_dir_value = config.get("directory")
    if not isinstance(tuple_dir_value, str) or not tuple_dir_value:
        raise WolfBootBuildProfileError("build.signing_tuple.directory must be a non-empty path")
    tuple_dir = repo_root / tuple_dir_value
    paths = {
        "directory": tuple_dir,
        "private_key": tuple_dir / str(config.get("private_key", "private_key.der")),
        "keystore": tuple_dir / str(config.get("keystore", "keystore.c")),
        "manifest": tuple_dir / str(config.get("manifest", "tuple.json")),
        "materialized_private_key": _resolve_wolfboot_private_key_path(
            repo_root=repo_root, source_dir=source_dir, profile=profile
        ) or (source_dir / DEFAULT_WOLFBOOT_PRIVATE_KEY_RELATIVE_PATH),
        "materialized_keystore": repo_root
        / str(_optional_profile_path(profile, "build.generated_keystore") or "tools/wolfboot/src/keystore.c"),
    }
    public_key_value = config.get("public_key")
    if isinstance(public_key_value, str) and public_key_value:
        paths["public_key"] = tuple_dir / public_key_value
    standby_values = config.get("standby_private_keys", [])
    if not isinstance(standby_values, list):
        raise WolfBootBuildProfileError("build.signing_tuple.standby_private_keys must be a list")
    for index, value in enumerate(standby_values, start=1):
        if not isinstance(value, str) or not value:
            raise WolfBootBuildProfileError("standby private-key names must be non-empty strings")
        paths[f"standby_private_key_{index}"] = tuple_dir / value
    return paths


def _tuple_sha256(path: Path) -> str:
    return calculate_file_sha256(path)


def _load_and_validate_persistent_tuple(
    *,
    profile: dict[str, Any],
    paths: dict[str, Path],
) -> tuple[str, str | None]:
    members = [paths["private_key"], paths["keystore"], paths["manifest"]]
    if "public_key" in paths:
        members.insert(1, paths["public_key"])
    standby_path_keys = sorted(
        key for key in paths if key.startswith("standby_private_key_")
    )
    members.extend(paths[key] for key in standby_path_keys)
    present = [path.is_file() for path in members]
    if not any(present):
        return "absent", None
    if not all(present):
        missing = [str(path) for path, exists in zip(members, present) if not exists]
        return "partial", "Persistent signing tuple is partial; missing: " + ", ".join(missing)
    try:
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "invalid", f"Persistent signing tuple manifest is invalid: {exc}"
    expected_algorithm = str(profile.get("signature_algorithm", ""))
    if manifest.get("signature_algorithm") != expected_algorithm:
        return "incompatible", (
            "Persistent signing tuple algorithm does not match the selected profile: "
            f"{manifest.get('signature_algorithm')} != {expected_algorithm}"
        )
    expected_standby = len(standby_path_keys)
    if int(manifest.get("standby_signing_keys", 0)) != expected_standby:
        return "incompatible", (
            "Persistent signing tuple standby-key count does not match the selected profile: "
            f"{manifest.get('standby_signing_keys', 0)} != {expected_standby}"
        )
    hash_members = [
        ("private_key", "private_key_sha256"),
        ("keystore", "keystore_sha256"),
    ]
    if "public_key" in paths:
        hash_members.insert(1, ("public_key", "public_key_sha256"))
    standby_hashes = manifest.get("standby_private_key_sha256", [])
    if not isinstance(standby_hashes, list) or len(standby_hashes) != len(standby_path_keys):
        return "invalid", "Persistent signing tuple standby-key hash inventory is invalid"
    for index, key in enumerate(standby_path_keys):
        if standby_hashes[index] != _tuple_sha256(paths[key]):
            return "invalid", f"Persistent signing tuple hash mismatch for {paths[key]}"
    for key, manifest_key in hash_members:
        if manifest.get(manifest_key) != _tuple_sha256(paths[key]):
            return "invalid", f"Persistent signing tuple hash mismatch for {paths[key]}"
    parameters = ML_DSA_TUPLE_PARAMETERS.get(expected_algorithm)
    if parameters:
        for key in ["private_key", *standby_path_keys]:
            if paths[key].stat().st_size != parameters[1]:
                return "incompatible", (
                    f"Persistent {expected_algorithm} tuple has an incompatible raw key size: {paths[key]}. "
                    "Preserve this tuple and select a new tuple identity; do not replace its keys."
                )
    return "complete", None


def _materialize_persistent_tuple(paths: dict[str, Path]) -> None:
    members = [
        ("private_key", "materialized_private_key"),
        ("keystore", "materialized_keystore"),
    ]
    for source_key, destination_key in members:
        destination = paths[destination_key]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(paths[source_key], destination)


def _keystore_public_key_bytes(
    *,
    keystore_path: Path,
    expected_size: int,
) -> tuple[bytes | None, str | None]:
    try:
        source = keystore_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"Unable to read persistent keystore: {exc}"

    match = re.search(
        r"\.pubkey\s*=\s*\{(?P<body>.*?)\}\s*,",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        return None, (
            "Unable to locate the first .pubkey initializer in "
            f"{keystore_path}"
        )

    values = bytes(
        int(value, 16)
        for value in re.findall(r"0x([0-9a-fA-F]{2})", match.group("body"))
    )
    if len(values) != expected_size:
        return None, (
            "Persistent keystore public-key size does not match the configured "
            f"size: {len(values)} != {expected_size}"
        )
    return values, None


def _derive_tuple_public_key(
    *,
    profile: dict[str, Any],
    private_key_path: Path,
    keystore_path: Path,
) -> tuple[bytes | None, str | None]:
    config = _signing_tuple_config(profile) or {}
    export_format = config.get("public_key_export_format")
    size_value = config.get("public_key_size")

    if export_format != "wolfboot_raw_ecc_xy":
        return None, (
            "Unsupported persistent public-key export format: "
            f"{export_format}"
        )
    if not isinstance(size_value, int) or size_value <= 0:
        return None, (
            "build.signing_tuple.public_key_size must be a positive integer"
        )

    try:
        private_bytes = private_key_path.read_bytes()
    except OSError as exc:
        return None, f"Unable to read persistent private key: {exc}"

    expected_private_size = size_value + (size_value // 2)
    if len(private_bytes) != expected_private_size:
        return None, (
            "wolfBoot raw ECC private-key size does not match the configured "
            f"public-key size: {len(private_bytes)} != {expected_private_size}"
        )

    public_bytes = private_bytes[:size_value]
    keystore_bytes, keystore_error = _keystore_public_key_bytes(
        keystore_path=keystore_path,
        expected_size=size_value,
    )
    if keystore_error is not None:
        return None, keystore_error
    if public_bytes != keystore_bytes:
        return None, (
            "Derived public key does not match the public key embedded in "
            f"{keystore_path}; the persistent tuple may be mismatched"
        )
    return public_bytes, None


def _migrate_optional_public_key(
    *,
    profile: dict[str, Any],
    paths: dict[str, Path],
) -> str | None:
    if "public_key" not in paths:
        return None

    private_key = paths["private_key"]
    keystore = paths["keystore"]
    manifest_path = paths["manifest"]
    if not private_key.is_file() or not keystore.is_file() or not manifest_path.is_file():
        return None

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"Persistent signing tuple manifest is invalid: {exc}"

    public_path = paths["public_key"]
    public_hash = manifest.get("public_key_sha256")
    if public_path.is_file() and public_path.stat().st_size > 0 and isinstance(public_hash, str):
        return None

    public_bytes, error = _derive_tuple_public_key(
        profile=profile,
        private_key_path=private_key,
        keystore_path=keystore,
    )
    if error is not None:
        return error
    assert public_bytes is not None

    tuple_dir = paths["directory"]
    temp_public = tuple_dir / f".{public_path.name}.migrating"
    temp_manifest = tuple_dir / f".{manifest_path.name}.migrating"
    try:
        temp_public.write_bytes(public_bytes)
        manifest["public_key_sha256"] = _tuple_sha256(temp_public)
        manifest["public_key_format"] = "wolfboot_raw_ecc_xy"
        manifest["public_key_size"] = len(public_bytes)
        temp_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_public, public_path)
        os.replace(temp_manifest, manifest_path)
    finally:
        temp_public.unlink(missing_ok=True)
        temp_manifest.unlink(missing_ok=True)
    return None



def _persist_generated_tuple_atomically(
    *,
    profile: dict[str, Any],
    paths: dict[str, Path],
) -> str | None:
    generated = [
        paths["materialized_private_key"],
        paths["materialized_keystore"],
    ]
    missing = [str(path) for path in generated if not path.is_file()]
    if missing:
        return "wolfBoot build passed but generated signing tuple is incomplete; missing: " + ", ".join(missing)

    tuple_dir = paths["directory"]
    tuple_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{tuple_dir.name}.creating-", dir=tuple_dir.parent))
    try:
        private_dest = temp_dir / paths["private_key"].name
        keystore_dest = temp_dir / paths["keystore"].name
        shutil.copyfile(paths["materialized_private_key"], private_dest)
        shutil.copyfile(paths["materialized_keystore"], keystore_dest)
        public_dest = None
        if "public_key" in paths:
            public_dest = temp_dir / paths["public_key"].name
            public_bytes, public_key_error = _derive_tuple_public_key(
                profile=profile,
                private_key_path=private_dest,
                keystore_path=keystore_dest,
            )
            if public_key_error is not None:
                return public_key_error
            assert public_bytes is not None
            public_dest.write_bytes(public_bytes)
        config = _signing_tuple_config(profile) or {}
        manifest = {
            "schema_version": 1,
            "tuple_id": str(config.get("tuple_id", tuple_dir.name)),
            "signature_algorithm": str(profile.get("signature_algorithm", "")),
            "standby_signing_keys": 0,
            "private_key_sha256": _tuple_sha256(private_dest),
            "standby_private_key_sha256": [],
            "keystore_sha256": _tuple_sha256(keystore_dest),
        }
        if public_dest is not None:
            manifest["public_key_sha256"] = _tuple_sha256(public_dest)
            manifest["public_key_format"] = "wolfboot_raw_ecc_xy"
            manifest["public_key_size"] = public_dest.stat().st_size
        (temp_dir / paths["manifest"].name).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if tuple_dir.exists():
            return f"Persistent signing tuple appeared concurrently: {tuple_dir}"
        os.replace(temp_dir, tuple_dir)
        return None
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _create_multi_key_persistent_tuple(
    *,
    profile: dict[str, Any],
    paths: dict[str, Path],
    source_dir: Path,
) -> str | None:
    """Create a 2/3-key wolfBoot tuple atomically using the pinned keygen tool."""
    standby_path_keys = sorted(
        key for key in paths if key.startswith("standby_private_key_")
    )
    if not standby_path_keys:
        return None
    build = profile.get("build", {})
    option = str(build.get("standby_keygen_option", "")).strip()
    if not option:
        return "Multi-key wolfBoot tuple requires build.standby_keygen_option"

    tuple_dir = paths["directory"]
    tuple_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{tuple_dir.name}.creating-", dir=tuple_dir.parent))
    generated_keystore = paths["materialized_keystore"]
    generated_private = paths["materialized_private_key"]
    keygen = source_dir / "tools" / "keytools" / "keygen"
    if os.name == "nt" and not keygen.exists():
        keygen = keygen.with_suffix(".exe")
    try:
        make_result = subprocess.run(
            ["make", "keytools"], cwd=source_dir, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if make_result.returncode != 0:
            return "Unable to build wolfBoot keygen for multi-key tuple: " + make_result.stderr.strip()
        if not keygen.is_file():
            return f"wolfBoot keygen executable is unavailable: {keygen}"

        private_dest = temp_dir / paths["private_key"].name
        standby_dests = [temp_dir / paths[key].name for key in standby_path_keys]
        command = [str(keygen), option, "--force", "-g", str(private_dest)]
        for standby in standby_dests:
            command.extend(["-g", str(standby)])
        keygen_environment = os.environ.copy()
        parameters = ML_DSA_TUPLE_PARAMETERS.get(str(profile.get("signature_algorithm", "")))
        if parameters:
            # The parent Makefile does not export this setting to an independently
            # invoked keygen. Its default is level 2, even for a level-3 bootloader.
            keygen_environment["ML_DSA_LEVEL"] = str(parameters[0])
        keygen_result = subprocess.run(
            command, cwd=source_dir, text=True, env=keygen_environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if keygen_result.returncode != 0:
            return "wolfBoot multi-key keygen failed: " + keygen_result.stderr.strip()
        if not generated_keystore.is_file():
            return f"wolfBoot keygen did not create keystore: {generated_keystore}"

        if parameters and any(p.stat().st_size != parameters[1] for p in [private_dest, *standby_dests]):
            return "wolfBoot keygen produced an incompatible ML-DSA raw key size; tuple not published"
        keystore_dest = temp_dir / paths["keystore"].name
        shutil.copyfile(generated_keystore, keystore_dest)
        public_dest = None
        if "public_key" in paths:
            public_dest = temp_dir / paths["public_key"].name
            public_bytes, public_key_error = _derive_tuple_public_key(
                profile=profile,
                private_key_path=private_dest,
                keystore_path=keystore_dest,
            )
            if public_key_error is not None:
                return public_key_error
            assert public_bytes is not None
            public_dest.write_bytes(public_bytes)

        config = _signing_tuple_config(profile) or {}
        manifest = {
            "schema_version": 2,
            "tuple_id": str(config.get("tuple_id", tuple_dir.name)),
            "signature_algorithm": str(profile.get("signature_algorithm", "")),
            "standby_signing_keys": len(standby_dests),
            "private_key_sha256": _tuple_sha256(private_dest),
            "standby_private_key_sha256": [_tuple_sha256(path) for path in standby_dests],
            "keystore_sha256": _tuple_sha256(keystore_dest),
        }
        if public_dest is not None:
            manifest["public_key_sha256"] = _tuple_sha256(public_dest)
            manifest["public_key_format"] = "wolfboot_raw_ecc_xy"
            manifest["public_key_size"] = public_dest.stat().st_size
        (temp_dir / paths["manifest"].name).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if tuple_dir.exists():
            return f"Persistent signing tuple appeared concurrently: {tuple_dir}"
        os.replace(temp_dir, tuple_dir)
        _materialize_persistent_tuple(paths)
        return None
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        # The persistent tuple owns the private material. Keep only the normal
        # wolfBoot-local primary key and generated public keystore materialized.
        for standby in standby_path_keys:
            candidate = source_dir / paths[standby].name
            candidate.unlink(missing_ok=True)
        if paths["private_key"].is_file():
            generated_private.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(paths["private_key"], generated_private)
        if paths["keystore"].is_file():
            generated_keystore.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(paths["keystore"], generated_keystore)


def _prepare_persistent_signing_tuple(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    source_dir: Path,
) -> tuple[dict[str, Path] | None, str | None]:
    paths = _signing_tuple_paths(profile=profile, repo_root=repo_root, source_dir=source_dir)
    if paths is None:
        return None, None
    migration_error = _migrate_optional_public_key(
        profile=profile,
        paths=paths,
    )
    if migration_error is not None:
        return paths, migration_error
    state, error = _load_and_validate_persistent_tuple(profile=profile, paths=paths)
    if error is not None:
        return paths, error
    if state == "complete":
        _materialize_persistent_tuple(paths)
    elif state == "absent":
        _remove_wolfboot_generated_signing_artifacts(
            profile=profile, repo_root=repo_root, source_dir=source_dir
        )
        standby_count = len([key for key in paths if key.startswith("standby_private_key_")])
        if standby_count:
            creation_error = _create_multi_key_persistent_tuple(
                profile=profile, paths=paths, source_dir=source_dir
            )
            if creation_error is not None:
                return paths, creation_error
    return paths, None


def _decode_wolfboot_command_output(output: bytes | str | None) -> str:
    """Decode captured wolfBoot command output without failing on toolchain bytes.

    wolfBoot builds invoke host tools and cross-compilers through ``make``. Some
    environments can emit non-UTF-8 bytes in diagnostic output. Build evidence
    should preserve the command output as text, but invalid byte sequences must
    not crash the framework before the build result and log are recorded.
    """

    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return output.decode("utf-8", errors="replace")


def default_wolfboot_runner(command: list[str], cwd: Path) -> WolfBootCommandExecution:
    """Run a wolfBoot build command and capture stdout, stderr, and timing."""

    start = perf_counter()
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=False,
        capture_output=True,
        check=False,
    )
    return WolfBootCommandExecution(
        command=command,
        return_code=completed.returncode,
        stdout=_decode_wolfboot_command_output(completed.stdout),
        stderr=_decode_wolfboot_command_output(completed.stderr),
        duration_seconds=perf_counter() - start,
    )


def create_wolfboot_build_result_dir(
    profile_id: str,
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
) -> Path:
    """Create a result directory for one wolfBoot build attempt."""

    current_timestamp = timestamp or datetime.now().astimezone()
    base = Path(results_root) / DEFAULT_WOLFBOOT_RESULTS_SUBDIR
    base.mkdir(parents=True, exist_ok=True)
    stem = f"{current_timestamp.strftime('%Y-%m-%d_%H%M%S')}_{_safe_id_component(profile_id)}"
    result_dir = base / stem
    suffix = 1
    while result_dir.exists():
        suffix += 1
        result_dir = base / f"{stem}_{suffix:02d}"
    result_dir.mkdir(parents=True, exist_ok=False)
    return result_dir


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _path_relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _resolve_optional_repo_path(repo_root: Path, configured: str | None) -> Path | None:
    if configured in (None, ""):
        return None
    path = Path(str(configured))
    return path if path.is_absolute() else repo_root / path


def _resolve_wolfboot_private_key_path(
    *,
    repo_root: Path,
    source_dir: Path,
    profile: dict[str, Any],
) -> Path | None:
    configured = _optional_profile_path(profile, "build.wolfboot_private_key")
    if configured is not None:
        return _resolve_optional_repo_path(repo_root, configured)
    if _optional_profile_path(profile, "build.signing_key") is not None:
        return source_dir / DEFAULT_WOLFBOOT_PRIVATE_KEY_RELATIVE_PATH
    return None


def _sha256_if_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return calculate_file_sha256(path)


def _coordinate_wolfboot_signing_key_before_build(
    *,
    signing_key_path: Path | None,
    wolfboot_private_key_path: Path | None,
) -> str | None:
    if signing_key_path is None or wolfboot_private_key_path is None:
        return "No canonical signing key coordination was configured for this wolfBoot build profile."
    if signing_key_path.is_file():
        wolfboot_private_key_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(signing_key_path, wolfboot_private_key_path)
        return "Copied the configured canonical signing key into the wolfBoot private key path before build."
    return "Configured canonical signing key was absent before build; wolfBoot may generate local key material, which will be copied back to the canonical path after a successful build if present."


def _coordinate_wolfboot_signing_key_after_build(
    *,
    signing_key_path: Path | None,
    wolfboot_private_key_path: Path | None,
    return_code: int,
    persistent_tuple: bool = False,
) -> str | None:
    if signing_key_path is None or wolfboot_private_key_path is None:
        return None
    if return_code != 0:
        return "wolfBoot build did not pass; canonical signing key was not modified."
    if not wolfboot_private_key_path.is_file():
        return "wolfBoot private key was not found after build; canonical signing key was not modified."
    if persistent_tuple:
        if not signing_key_path.is_file():
            return "Persistent tuple key is unexpectedly absent after build; no write-back was attempted."
        canonical_sha256 = calculate_file_sha256(signing_key_path)
        materialized_sha256 = calculate_file_sha256(wolfboot_private_key_path)
        if canonical_sha256 != materialized_sha256:
            return "Persistent tuple key and materialized wolfBoot key differ after build; no write-back was attempted."
        return "Persistent tuple key remained authoritative and unchanged; post-build write-back was skipped."
    signing_key_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wolfboot_private_key_path, signing_key_path)
    return "Copied wolfBoot private key back to the configured legacy canonical signing-key path after successful build."


def _key_consistency_evidence(
    *,
    signing_key_path: Path | None,
    wolfboot_private_key_path: Path | None,
) -> tuple[str, str | None, str | None, str | None]:
    signing_key_sha256 = _sha256_if_file(signing_key_path)
    wolfboot_private_key_sha256 = _sha256_if_file(wolfboot_private_key_path)
    if signing_key_path is None and wolfboot_private_key_path is None:
        return "not_configured", "No signing-key coordination paths are configured.", signing_key_sha256, wolfboot_private_key_sha256
    if signing_key_sha256 is None or wolfboot_private_key_sha256 is None:
        return "unavailable", "One or both configured local signing-key files are unavailable.", signing_key_sha256, wolfboot_private_key_sha256
    if signing_key_sha256 != wolfboot_private_key_sha256:
        return "mismatch", "Configured canonical signing key and wolfBoot private key differ.", signing_key_sha256, wolfboot_private_key_sha256
    return "matched", "Configured canonical signing key and wolfBoot private key match.", signing_key_sha256, wolfboot_private_key_sha256


def _fingerprint_evidence(
    *,
    repo_root: Path,
    profile: dict[str, Any],
    source_dir: Path,
    config_template_path: Path | None,
) -> dict[str, Any]:
    profile_id = str(profile.get("id", "unknown"))
    requested_inputs = default_wolfboot_fingerprint_inputs(
        profile_id=profile_id,
        source_dir=_path_relative_to_repo(source_dir, repo_root),
        config_template=None
        if config_template_path is None
        else _path_relative_to_repo(config_template_path, repo_root),
    )
    missing_inputs = [
        relative_input
        for relative_input in requested_inputs
        if not (repo_root / relative_input).exists()
    ]
    try:
        fingerprint = calculate_existing_inputs_fingerprint(
            repo_root=repo_root,
            relative_inputs=requested_inputs,
        )
    except FingerprintInputError as exc:
        return {
            "status": "unavailable",
            "fingerprint": None,
            "fingerprint_algorithm": None,
            "fingerprint_inputs": [],
            "fingerprint_file_hashes": {},
            "fingerprint_tool_versions": {},
            "requested_fingerprint_inputs": requested_inputs,
            "missing_fingerprint_inputs": missing_inputs,
            "limitations": str(exc),
        }
    return {
        "status": "available",
        "fingerprint": fingerprint.fingerprint,
        "fingerprint_algorithm": fingerprint.algorithm,
        "fingerprint_inputs": fingerprint.inputs,
        "fingerprint_file_hashes": fingerprint.file_hashes,
        "fingerprint_tool_versions": fingerprint.tool_versions or {},
        "requested_fingerprint_inputs": requested_inputs,
        "missing_fingerprint_inputs": missing_inputs,
        "limitations": None
        if not missing_inputs
        else "Some optional wolfBoot source inputs were absent and therefore not hashed; fingerprint_inputs lists the exact files covered.",
    }


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _write_log(
    *,
    log_path: Path,
    profile: dict[str, Any],
    repo_root: Path,
    command: list[str],
    working_directory: Path,
    source_dir: Path,
    output_dir: Path,
    artifact_path: Path,
    artifact_exists: bool,
    artifact_sha256: str | None,
    config_template_path: Path | None,
    generated_config_path: Path | None,
    config_applied: bool,
    keytools_mingw_stdio_patch_enabled: bool,
    keytools_mingw_stdio_patch_applied: bool,
    keytools_makefile_path: Path | None,
    stm32l4_hal_conf_pwr_patch_enabled: bool,
    stm32l4_hal_conf_pwr_patch_applied: bool,
    stm32l4_hal_conf_path: Path | None,
    boot_timing_instrumentation_patch_enabled: bool,
    boot_timing_instrumentation_patch_applied: bool,
    boot_timing_image_path: Path | None,
    boot_timing_hal_path: Path | None,
    return_code: int,
    duration_seconds: float,
    execution: WolfBootCommandExecution | None,
    failure_reason: str | None,
    fingerprint_evidence: dict[str, Any] | None = None,
    signing_key_path: Path | None = None,
    wolfboot_private_key_path: Path | None = None,
    signing_key_sha256: str | None = None,
    wolfboot_private_key_sha256: str | None = None,
    key_consistency_status: str = "not_configured",
    key_consistency_message: str | None = None,
    key_sync_before_build_message: str | None = None,
    key_sync_after_build_message: str | None = None,
    generated_signing_artifact_cleanup_paths: list[Path] | None = None,
) -> None:
    lines = [
        "wolfBoot build log",
        "==================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Profile ID: {profile.get('id')}",
        f"Repository root: {repo_root}",
        f"Source directory: {source_dir}",
        f"Output directory: {output_dir}",
        f"Configured target: {profile.get('target')}",
        f"Signature algorithm: {profile.get('signature_algorithm')}",
        f"Command: {_format_command(command) if command else 'unavailable'}",
        f"Working directory: {working_directory}",
        f"Artifact path: {artifact_path}",
        f"Artifact exists: {str(artifact_exists).lower()}",
        f"Artifact SHA-256: {artifact_sha256 if artifact_sha256 is not None else 'unavailable'}",
        f"Canonical signing key path: {signing_key_path if signing_key_path is not None else 'not configured'}",
        f"wolfBoot private key path: {wolfboot_private_key_path if wolfboot_private_key_path is not None else 'not configured'}",
        f"Canonical signing key SHA-256: {signing_key_sha256 if signing_key_sha256 is not None else 'unavailable'}",
        f"wolfBoot private key SHA-256: {wolfboot_private_key_sha256 if wolfboot_private_key_sha256 is not None else 'unavailable'}",
        f"Signing key consistency status: {key_consistency_status}",
        f"Signing key consistency message: {key_consistency_message if key_consistency_message is not None else 'none'}",
        f"Signing key sync before build: {key_sync_before_build_message if key_sync_before_build_message is not None else 'none'}",
        f"Signing key sync after build: {key_sync_after_build_message if key_sync_after_build_message is not None else 'none'}",
        "Private signing keys are local-only evidence inputs and are not copied into the result directory.",
        f"Generated wolfBoot signing artifact cleanup count: {len(generated_signing_artifact_cleanup_paths or [])}",
        f"Generated wolfBoot signing artifact cleanup paths: {', '.join(str(path) for path in (generated_signing_artifact_cleanup_paths or [])) if generated_signing_artifact_cleanup_paths else 'none'}",
        f"Input fingerprint status: {fingerprint_evidence.get('status') if fingerprint_evidence else 'unavailable'}",
        f"Input fingerprint algorithm: {fingerprint_evidence.get('fingerprint_algorithm') if fingerprint_evidence else 'unavailable'}",
        f"Input fingerprint: {fingerprint_evidence.get('fingerprint') if fingerprint_evidence else 'unavailable'}",
        f"Input fingerprint file count: {len(fingerprint_evidence.get('fingerprint_inputs', [])) if fingerprint_evidence else 0}",
        f"Config template path: {config_template_path if config_template_path is not None else 'unavailable'}",
        f"Generated config path: {generated_config_path if generated_config_path is not None else 'unavailable'}",
        f"Project-local config applied: {str(config_applied).lower()}",
        f"Keytools MinGW stdio patch enabled: {str(keytools_mingw_stdio_patch_enabled).lower()}",
        f"Keytools MinGW stdio patch applied: {str(keytools_mingw_stdio_patch_applied).lower()}",
        f"Keytools Makefile path: {keytools_makefile_path if keytools_makefile_path is not None else 'unavailable'}",
        f"STM32L4 HAL config PWR patch enabled: {str(stm32l4_hal_conf_pwr_patch_enabled).lower()}",
        f"STM32L4 HAL config PWR patch applied: {str(stm32l4_hal_conf_pwr_patch_applied).lower()}",
        f"STM32L4 HAL config path: {stm32l4_hal_conf_path if stm32l4_hal_conf_path is not None else 'unavailable'}",
        f"Boot timing instrumentation patch enabled: {str(boot_timing_instrumentation_patch_enabled).lower()}",
        f"Boot timing instrumentation patch applied: {str(boot_timing_instrumentation_patch_applied).lower()}",
        f"Boot timing image source path: {boot_timing_image_path if boot_timing_image_path is not None else 'unavailable'}",
        f"Boot timing HAL source path: {boot_timing_hal_path if boot_timing_hal_path is not None else 'unavailable'}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
    ]

    if failure_reason is not None:
        lines.extend(["", "Failure reason", "--------------", failure_reason])

    if execution is not None:
        lines.extend(
            [
                "",
                "Build command output",
                "--------------------",
                f"Return code: {execution.return_code}",
                f"Duration seconds: {execution.duration_seconds:.3f}",
                "",
                "stdout:",
                execution.stdout.rstrip(),
                "",
                "stderr:",
                execution.stderr.rstrip(),
                "",
            ]
        )

    log_path.write_text("\n".join(lines), encoding="utf-8")


def execute_wolfboot_build(
    *,
    profile: dict[str, Any],
    repo_root: Path | str,
    results_root: Path | str = "results",
    runner: WolfBootRunner = default_wolfboot_runner,
    timestamp: datetime | None = None,
) -> WolfBootBuildResult:
    """Execute a configured wolfBoot build profile and record evidence."""

    repo_root_path = Path(repo_root)
    start = perf_counter()

    try:
        validate_wolfboot_build_profile(profile)
        command = construct_wolfboot_build_command(profile)
        profile_id = str(profile["id"])
    except WolfBootBuildProfileError as exc:
        profile_id = str(profile.get("id", "invalid_wolfboot_profile"))
        result_dir = create_wolfboot_build_result_dir(profile_id, results_root, timestamp)
        log_path = result_dir / DEFAULT_WOLFBOOT_LOG_NAME
        duration_seconds = perf_counter() - start
        failure_reason = str(exc)
        manifest = {
            "record_type": "wolfboot_build",
            "schema_version": 1,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "profile": profile_id,
            "result": "wolfboot_build_failed",
            "wolfboot_build": {
                "return_code": PROFILE_ERROR_RETURN_CODE,
                "duration_seconds": round(duration_seconds, 3),
                "log": DEFAULT_WOLFBOOT_LOG_NAME,
                "failure_reason": failure_reason,
            },
        }
        _write_log(
            log_path=log_path,
            profile=profile,
            repo_root=repo_root_path,
            command=[],
            working_directory=repo_root_path,
            source_dir=repo_root_path,
            output_dir=repo_root_path,
            artifact_path=repo_root_path,
            artifact_exists=False,
            artifact_sha256=None,
            config_template_path=None,
            generated_config_path=None,
            config_applied=False,
            keytools_mingw_stdio_patch_enabled=False,
            keytools_mingw_stdio_patch_applied=False,
            keytools_makefile_path=None,
            stm32l4_hal_conf_pwr_patch_enabled=False,
            stm32l4_hal_conf_pwr_patch_applied=False,
            stm32l4_hal_conf_path=None,
            boot_timing_instrumentation_patch_enabled=False,
            boot_timing_instrumentation_patch_applied=False,
            boot_timing_image_path=None,
            boot_timing_hal_path=None,
            return_code=PROFILE_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            execution=None,
            failure_reason=failure_reason,
        )
        _write_json(result_dir / "manifest.json", manifest)
        return WolfBootBuildResult(
            return_code=PROFILE_ERROR_RETURN_CODE,
            duration_seconds=duration_seconds,
            profile_id=profile_id,
            result_dir=result_dir,
            log_path=log_path,
            command=[],
            working_directory=repo_root_path,
            source_dir=repo_root_path,
            output_dir=repo_root_path,
            artifact_path=repo_root_path,
            artifact_exists=False,
            artifact_sha256=None,
            config_template_path=None,
            generated_config_path=None,
            config_applied=False,
            keytools_mingw_stdio_patch_enabled=False,
            keytools_mingw_stdio_patch_applied=False,
            keytools_makefile_path=None,
            stm32l4_hal_conf_pwr_patch_enabled=False,
            stm32l4_hal_conf_pwr_patch_applied=False,
            stm32l4_hal_conf_path=None,
            boot_timing_instrumentation_patch_enabled=False,
            boot_timing_instrumentation_patch_applied=False,
            boot_timing_image_path=None,
            boot_timing_hal_path=None,
            retained_artifact_path=None,
            signing_key_path=None,
            wolfboot_private_key_path=None,
            signing_key_sha256=None,
            wolfboot_private_key_sha256=None,
            key_consistency_status="not_configured",
            key_consistency_message=None,
            execution=None,
            failure_reason=failure_reason,
        )

    source_dir = repo_root_path / str(profile["source_dir"])
    output_dir = repo_root_path / str(profile["output_dir"])
    artifact_path = repo_root_path / str(profile["artifact"])
    config_template_path: Path | None = None
    generated_config_path: Path | None = None
    config_applied = False
    keytools_mingw_stdio_patch_enabled = _optional_profile_bool(profile, "build.mingw_keytools_ansi_stdio_patch")
    keytools_mingw_stdio_patch_applied = False
    keytools_makefile_path: Path | None = None
    keytools_makefile_original_text: str | None = None
    stm32l4_hal_conf_pwr_patch_enabled = _optional_profile_bool(profile, "build.stm32l4_hal_conf_pwr_patch")
    stm32l4_hal_conf_pwr_patch_applied = False
    stm32l4_hal_conf_path: Path | None = None
    stm32l4_hal_conf_original_text: str | None = None
    boot_timing_instrumentation_patch_enabled = _optional_profile_bool(profile, "build.boot_timing_instrumentation_patch")
    boot_timing_instrumentation_patch_applied = False
    boot_timing_image_path: Path | None = None
    boot_timing_hal_path: Path | None = None
    boot_timing_image_original_text: str | None = None
    boot_timing_hal_original_text: str | None = None
    working_directory = source_dir
    result_dir = create_wolfboot_build_result_dir(profile_id, results_root, timestamp)
    log_path = result_dir / DEFAULT_WOLFBOOT_LOG_NAME
    signing_key_path = _resolve_optional_repo_path(
        repo_root_path,
        str(_optional_profile_path(profile, "build.signing_key") or ""),
    )
    wolfboot_private_key_path = _resolve_wolfboot_private_key_path(
        repo_root=repo_root_path,
        source_dir=source_dir,
        profile=profile,
    )
    key_sync_before_build_message: str | None = None
    generated_signing_artifact_cleanup_paths: list[Path] = []
    persistent_tuple_paths: dict[str, Path] | None = None

    execution: WolfBootCommandExecution | None = None
    artifact_sha256: str | None = None
    retained_artifact_path: Path | None = None
    retained_binary_path: Path | None = None
    binary_artifact_path: Path | None = None
    binary_artifact_sha256: str | None = None
    binary_conversion: dict[str, Any] | None = None
    failure_reason: str | None = None
    wolfboot_state_identity: dict[str, Any] | None = None
    fingerprint_evidence: dict[str, Any] = {
        "status": "unavailable",
        "fingerprint": None,
        "fingerprint_algorithm": None,
        "fingerprint_inputs": [],
        "requested_fingerprint_inputs": [],
        "missing_fingerprint_inputs": [],
        "limitations": "wolfBoot source directory was not inspected before fingerprinting.",
    }

    if not source_dir.is_dir():
        return_code = MISSING_SOURCE_RETURN_CODE
        failure_reason = f"Configured wolfBoot source directory does not exist: {source_dir}"
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            config_template_path, generated_config_path, config_applied = _copy_project_local_config(
                profile=profile,
                repo_root=repo_root_path,
                source_dir=source_dir,
            )
        except WolfBootBuildProfileError as exc:
            return_code = PROFILE_ERROR_RETURN_CODE
            failure_reason = str(exc)
        else:
            fingerprint_evidence = _fingerprint_evidence(
                repo_root=repo_root_path,
                profile=profile,
                source_dir=source_dir,
                config_template_path=config_template_path,
            )
            public_key_path = source_dir / "wolfboot_signing_public_key.der"
            generated_keystore_config = _optional_profile_path(profile, "build.generated_keystore")
            generated_keystore_path = (
                repo_root_path / generated_keystore_config
                if generated_keystore_config is not None
                else source_dir / "src" / "keystore.c"
            )
            wolfboot_state_identity = build_identity(
                workflow="wolfboot_build",
                profile=profile_id,
                input_fingerprint=fingerprint_evidence,
                toolchain={"command": command, "target": profile.get("target")},
                execution=detect_execution_identity(),
                key_tuple=key_tuple_fingerprint(
                    private_key=wolfboot_private_key_path,
                    public_key=public_key_path,
                    keystore=generated_keystore_path,
                ),
                extra={"signature_algorithm": profile.get("signature_algorithm"),
                       "runtime_stack_high_water_instrumentation": _optional_profile_bool(profile, "build.runtime_stack_high_water_instrumentation"),
                       "boot_uart_diagnostics": _optional_profile_bool(profile, "build.boot_uart_diagnostics")},
            )
            generated_cleanup_paths = [
                path
                for pattern in (
                    *WOLFBOOT_HOST_TOOL_OUTPUT_PATTERNS,
                    *WOLFBOOT_PROFILE_DEPENDENT_OUTPUT_PATTERNS,
                )
                for path in source_dir.glob(pattern)
            ]
            preflight_generated_state(
                repo_root=repo_root_path,
                scope=f"wolfboot-{profile_id}",
                expected_identity=wolfboot_state_identity,
                cleanup_paths=generated_cleanup_paths,
                final_artifact_paths=[artifact_path],
            )
            try:
                (
                    keytools_makefile_path,
                    keytools_mingw_stdio_patch_applied,
                    keytools_makefile_original_text,
                ) = _temporarily_patch_keytools_makefile(
                    profile=profile,
                    source_dir=source_dir,
                )
            except WolfBootBuildProfileError as exc:
                return_code = PROFILE_ERROR_RETURN_CODE
                failure_reason = str(exc)
            else:
                try:
                    try:
                        (
                            stm32l4_hal_conf_path,
                            stm32l4_hal_conf_pwr_patch_applied,
                            stm32l4_hal_conf_original_text,
                        ) = _temporarily_patch_stm32l4_hal_conf(
                            profile=profile,
                            source_dir=source_dir,
                        )
                    except WolfBootBuildProfileError as exc:
                        return_code = PROFILE_ERROR_RETURN_CODE
                        failure_reason = str(exc)
                    else:
                        try:
                            (
                                boot_timing_image_path,
                                boot_timing_hal_path,
                                boot_timing_instrumentation_patch_applied,
                                boot_timing_image_original_text,
                                boot_timing_hal_original_text,
                            ) = _temporarily_patch_boot_timing_instrumentation(
                                profile=profile,
                                source_dir=source_dir,
                            )
                        except WolfBootBuildProfileError as exc:
                            return_code = PROFILE_ERROR_RETURN_CODE
                            failure_reason = str(exc)
                        else:
                            try:
                                _remove_wolfboot_host_tool_outputs(source_dir)
                                if _requires_signing_material(profile):
                                    persistent_tuple_paths, signing_artifact_error = (
                                        _prepare_persistent_signing_tuple(
                                            profile=profile,
                                            repo_root=repo_root_path,
                                            source_dir=source_dir,
                                        )
                                    )
                                    if persistent_tuple_paths is None:
                                        (
                                            generated_signing_artifact_cleanup_paths,
                                            signing_artifact_error,
                                        ) = _prepare_wolfboot_signing_artifacts(
                                            profile=profile,
                                            repo_root=repo_root_path,
                                            source_dir=source_dir,
                                            signing_key_path=signing_key_path,
                                            wolfboot_private_key_path=wolfboot_private_key_path,
                                        )
                                    if signing_artifact_error is None:
                                        key_sync_before_build_message = (
                                            _coordinate_wolfboot_signing_key_before_build(
                                                signing_key_path=signing_key_path,
                                                wolfboot_private_key_path=wolfboot_private_key_path,
                                            )
                                        )
                                else:
                                    persistent_tuple_paths = None
                                    signing_artifact_error = None
                                    generated_signing_artifact_cleanup_paths = []
                                    key_sync_before_build_message = (
                                        "Integrity-only wolfBoot profile does not use signing material."
                                    )

                                if signing_artifact_error is not None:
                                    return_code = PROFILE_ERROR_RETURN_CODE
                                    failure_reason = signing_artifact_error
                                else:
                                    execution = runner(command, working_directory)
                                    return_code = execution.return_code
                                    if return_code == 0 and persistent_tuple_paths is not None:
                                        tuple_state, tuple_error = _load_and_validate_persistent_tuple(
                                            profile=profile,
                                            paths=persistent_tuple_paths,
                                        )
                                        if tuple_state == "absent" and tuple_error is None:
                                            tuple_error = _persist_generated_tuple_atomically(
                                                profile=profile,
                                                paths=persistent_tuple_paths,
                                            )
                                        if tuple_error is not None:
                                            return_code = PROFILE_ERROR_RETURN_CODE
                                            failure_reason = tuple_error
                                        elif tuple_state == "complete":
                                            _materialize_persistent_tuple(persistent_tuple_paths)
                            except FileNotFoundError as exc:
                                missing_executable = command[0] if command else "configured build tool"
                                return_code = WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE
                                failure_reason = (
                                    "wolfBoot build command could not be started because the executable was not found: "
                                    f"{missing_executable}"
                                )
                                execution = WolfBootCommandExecution(
                                    command=command,
                                    return_code=return_code,
                                    stdout="",
                                    stderr=f"{failure_reason}\n{exc}",
                                    duration_seconds=perf_counter() - start,
                                )
                finally:
                    if boot_timing_image_original_text is not None and boot_timing_image_path is not None:
                        boot_timing_image_path.write_text(
                            boot_timing_image_original_text,
                            encoding="utf-8",
                        )
                    if boot_timing_hal_original_text is not None and boot_timing_hal_path is not None:
                        boot_timing_hal_path.write_text(
                            boot_timing_hal_original_text,
                            encoding="utf-8",
                        )
                    if stm32l4_hal_conf_original_text is not None and stm32l4_hal_conf_path is not None:
                        stm32l4_hal_conf_path.write_text(
                            stm32l4_hal_conf_original_text,
                            encoding="utf-8",
                        )
                    if keytools_makefile_original_text is not None and keytools_makefile_path is not None:
                        keytools_makefile_path.write_text(
                            keytools_makefile_original_text,
                            encoding="utf-8",
                        )

        if return_code == 0:
            if artifact_path.is_file():
                artifact_sha256 = calculate_file_sha256(artifact_path)
                binary_artifact_path = artifact_path.with_suffix(".bin")
                binary_command = [
                    "arm-none-eabi-objcopy",
                    "-O",
                    "binary",
                    str(artifact_path),
                    str(binary_artifact_path),
                ]
                binary_start = perf_counter()
                try:
                    completed = subprocess.run(
                        binary_command,
                        cwd=working_directory,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    binary_conversion = {
                        "command": binary_command,
                        "return_code": completed.returncode,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                        "duration_seconds": round(perf_counter() - binary_start, 3),
                    }
                    if completed.returncode != 0 or not binary_artifact_path.is_file():
                        return_code = WOLFBOOT_BINARY_CONVERSION_FAILED_RETURN_CODE
                        failure_reason = (
                            "wolfBoot ELF build succeeded, but raw bootloader binary conversion failed. "
                            f"objcopy return code: {completed.returncode}; expected artifact: {binary_artifact_path}"
                        )
                except FileNotFoundError as exc:
                    binary_conversion = {
                        "command": binary_command,
                        "return_code": WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE,
                        "stdout": "",
                        "stderr": str(exc),
                        "duration_seconds": round(perf_counter() - binary_start, 3),
                    }
                    return_code = WOLFBOOT_BINARY_CONVERSION_FAILED_RETURN_CODE
                    failure_reason = (
                        "wolfBoot ELF build succeeded, but arm-none-eabi-objcopy was not available "
                        "to create the required raw bootloader binary."
                    )

                if return_code == 0:
                    binary_artifact_sha256 = calculate_file_sha256(binary_artifact_path)
                    retained_artifact_path = copy_artifact_to_result(
                        artifact_path,
                        result_dir,
                        "wolfboot.elf",
                    )
                    retained_binary_path = copy_artifact_to_result(
                        binary_artifact_path,
                        result_dir,
                        "wolfboot.bin",
                    )
            else:
                return_code = WOLFBOOT_BUILD_ARTIFACT_MISSING_RETURN_CODE
                failure_reason = (
                    "wolfBoot build command returned success, but the configured artifact was not found: "
                    f"{artifact_path}"
                )
        elif failure_reason is None:
            failure_reason = f"wolfBoot build command failed with return code {return_code}."

    if _requires_signing_material(profile):
        key_sync_after_build_message = _coordinate_wolfboot_signing_key_after_build(
            signing_key_path=signing_key_path,
            wolfboot_private_key_path=wolfboot_private_key_path,
            return_code=return_code,
            persistent_tuple=persistent_tuple_paths is not None,
        )
    else:
        key_sync_after_build_message = (
            "Integrity-only wolfBoot profile does not use signing material."
        )
    (
        key_consistency_status,
        key_consistency_message,
        signing_key_sha256,
        wolfboot_private_key_sha256,
    ) = _key_consistency_evidence(
        signing_key_path=signing_key_path,
        wolfboot_private_key_path=wolfboot_private_key_path,
    )

    if return_code == 0 and persistent_tuple_paths is not None:
        append_signing_usage_event(
            tuple_directory=persistent_tuple_paths["directory"],
            event={
                "event": "wolfboot_verification_key_use",
                "profile_id": profile_id,
                "signature_algorithm": profile.get("signature_algorithm"),
                "private_key_sha256": signing_key_sha256,
                "artifact_path": str(artifact_path),
                "artifact_sha256": artifact_sha256,
                "result_directory": str(result_dir),
                "purpose": "build wolfBoot with the tuple public key embedded in keystore.c",
                "private_key_modified": False,
            },
        )

    if return_code == 0 and wolfboot_state_identity is not None:
        state_artifacts = [artifact_path]
        if binary_artifact_path is not None and binary_artifact_path.is_file():
            state_artifacts.append(binary_artifact_path)
        record_generated_state_success(
            repo_root=repo_root_path,
            scope=f"wolfboot-{profile_id}",
            identity=wolfboot_state_identity,
            artifacts=state_artifacts,
            record_refs={"wolfboot_build_manifest": str(result_dir / "manifest.json")},
        )

    result_materials: list[dict[str, Any]] = []
    material_inventory_path: Path | None = None
    if return_code == 0:
        result_materials.append(copy_material_to_result(
            artifact_path, result_dir, "artifacts/bootloader/wolfboot.elf",
            role="bootloader_elf", required_for=["manual_flash", "debugging"],
        ))
        for suffix in (".bin", ".hex"):
            sibling = artifact_path.with_suffix(suffix)
            if sibling.is_file():
                result_materials.append(copy_material_to_result(
                    sibling, result_dir, f"artifacts/bootloader/wolfboot{suffix}",
                    role=f"bootloader_{suffix.lstrip('.')}", required_for=["manual_flash"],
                ))
        if persistent_tuple_paths is not None:
            result_materials.extend(copy_material_directory_to_result(
                persistent_tuple_paths["directory"], result_dir,
                "cryptographic-material/bootloader-signing/tuple",
                role_prefix="bootloader_signing_tuple",
                private_names={persistent_tuple_paths["private_key"].name, "private_key.der", "private_key.pem"},
                required_for=["repeat_bootloader_build", "repeat_signing", "signature_verification"],
            ))
        else:
            for source, destination, role, private in (
                (signing_key_path, "cryptographic-material/bootloader-signing/private/canonical_private_key.der", "bootloader_signing_private_key", True),
                (wolfboot_private_key_path, "cryptographic-material/bootloader-signing/private/wolfboot_private_key.der", "bootloader_working_private_key", True),
                (source_dir / "wolfboot_signing_public_key.der", "cryptographic-material/bootloader-signing/public/wolfboot_public_key.der", "bootloader_signing_public_key", False),
                (source_dir / "src" / "keystore.c", "cryptographic-material/bootloader-signing/verification/keystore.c", "bootloader_verification_keystore", False),
            ):
                if source is not None and source.is_file():
                    result_materials.append(copy_material_to_result(
                        source, result_dir, destination, role=role, private=private,
                        required_for=["repeat_bootloader_build", "signature_verification"],
                    ))
        material_inventory_path = write_material_inventory(result_dir, result_materials)

    duration_seconds = perf_counter() - start
    artifact_exists = artifact_path.is_file()
    _write_log(
        log_path=log_path,
        profile=profile,
        repo_root=repo_root_path,
        command=command,
        working_directory=working_directory,
        source_dir=source_dir,
        output_dir=output_dir,
        artifact_path=artifact_path,
        artifact_exists=artifact_exists,
        artifact_sha256=artifact_sha256,
        config_template_path=config_template_path,
        generated_config_path=generated_config_path,
        config_applied=config_applied,
        keytools_mingw_stdio_patch_enabled=keytools_mingw_stdio_patch_enabled,
        keytools_mingw_stdio_patch_applied=keytools_mingw_stdio_patch_applied,
        keytools_makefile_path=keytools_makefile_path,
        stm32l4_hal_conf_pwr_patch_enabled=stm32l4_hal_conf_pwr_patch_enabled,
        stm32l4_hal_conf_pwr_patch_applied=stm32l4_hal_conf_pwr_patch_applied,
        stm32l4_hal_conf_path=stm32l4_hal_conf_path,
        boot_timing_instrumentation_patch_enabled=boot_timing_instrumentation_patch_enabled,
        boot_timing_instrumentation_patch_applied=boot_timing_instrumentation_patch_applied,
        boot_timing_image_path=boot_timing_image_path,
        boot_timing_hal_path=boot_timing_hal_path,
        return_code=return_code,
        duration_seconds=duration_seconds,
        execution=execution,
        failure_reason=failure_reason,
        fingerprint_evidence=fingerprint_evidence,
        signing_key_path=signing_key_path,
        wolfboot_private_key_path=wolfboot_private_key_path,
        signing_key_sha256=signing_key_sha256,
        wolfboot_private_key_sha256=wolfboot_private_key_sha256,
        key_consistency_status=key_consistency_status,
        key_consistency_message=key_consistency_message,
        key_sync_before_build_message=key_sync_before_build_message,
        key_sync_after_build_message=key_sync_after_build_message,
        generated_signing_artifact_cleanup_paths=generated_signing_artifact_cleanup_paths,
    )

    manifest = {
        "record_type": "wolfboot_build",
        "schema_version": 1,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "profile": profile_id,
        "result": "wolfboot_build_passed" if return_code == 0 else "wolfboot_build_failed",
        "wolfboot_build": {
            "profile_id": profile_id,
            "description": profile.get("description"),
            "target": profile.get("target"),
            "signature_algorithm": profile.get("signature_algorithm"),
            "source_dir": str(source_dir),
            "output_dir": str(output_dir),
            "command": command,
            "working_directory": str(working_directory),
            "return_code": return_code,
            "duration_seconds": round(duration_seconds, 3),
            "log": DEFAULT_WOLFBOOT_LOG_NAME,
            "failure_reason": failure_reason,
            "signing_key_path": None if signing_key_path is None else str(signing_key_path),
            "wolfboot_private_key_path": None if wolfboot_private_key_path is None else str(wolfboot_private_key_path),
            "signing_key_sha256": signing_key_sha256,
            "wolfboot_private_key_sha256": wolfboot_private_key_sha256,
            "key_consistency_status": key_consistency_status,
            "key_consistency_message": key_consistency_message,
            "key_sync_before_build_message": key_sync_before_build_message,
            "key_sync_after_build_message": key_sync_after_build_message,
            "generated_signing_artifact_cleanup": {
                "enabled": True,
                "removed_count": len(generated_signing_artifact_cleanup_paths),
                "removed_paths": [str(path) for path in generated_signing_artifact_cleanup_paths],
            },
            "key_material_copied_to_results": bool(result_materials),
            "material_inventory": None if material_inventory_path is None else material_inventory_path.name,
            "result_materials": result_materials,
            "fingerprint": fingerprint_evidence.get("fingerprint"),
            "fingerprint_algorithm": fingerprint_evidence.get("fingerprint_algorithm"),
            "fingerprint_inputs": fingerprint_evidence.get("fingerprint_inputs", []),
                "fingerprint_file_hashes": fingerprint_evidence.get("fingerprint_file_hashes", {}),
                "fingerprint_tool_versions": fingerprint_evidence.get("fingerprint_tool_versions", {}),
            "requested_fingerprint_inputs": fingerprint_evidence.get("requested_fingerprint_inputs", []),
            "missing_fingerprint_inputs": fingerprint_evidence.get("missing_fingerprint_inputs", []),
            "fingerprint_status": fingerprint_evidence.get("status"),
            "fingerprint_limitations": fingerprint_evidence.get("limitations"),
            "config_template": None if config_template_path is None else str(config_template_path),
            "generated_config": None if generated_config_path is None else str(generated_config_path),
            "config_applied": config_applied,
            "keytools_mingw_stdio_patch_enabled": keytools_mingw_stdio_patch_enabled,
            "keytools_mingw_stdio_patch_applied": keytools_mingw_stdio_patch_applied,
            "keytools_makefile": None if keytools_makefile_path is None else str(keytools_makefile_path),
            "stm32l4_hal_conf_pwr_patch_enabled": stm32l4_hal_conf_pwr_patch_enabled,
            "stm32l4_hal_conf_pwr_patch_applied": stm32l4_hal_conf_pwr_patch_applied,
            "stm32l4_hal_conf_path": None if stm32l4_hal_conf_path is None else str(stm32l4_hal_conf_path),
            "runtime_stack_high_water_instrumentation": _optional_profile_bool(profile, "build.runtime_stack_high_water_instrumentation"),
            "boot_uart_diagnostics": _optional_profile_bool(profile, "build.boot_uart_diagnostics"),
            "timing_comparison_eligible": not _optional_profile_bool(profile, "build.boot_uart_diagnostics"),
            "boot_timing_instrumentation_patch_enabled": boot_timing_instrumentation_patch_enabled,
            "boot_timing_instrumentation_patch_applied": boot_timing_instrumentation_patch_applied,
            "boot_timing_image_path": None if boot_timing_image_path is None else str(boot_timing_image_path),
            "boot_timing_hal_path": None if boot_timing_hal_path is None else str(boot_timing_hal_path),
        },
        "signing_key_consistency": {
            "status": key_consistency_status,
            "message": key_consistency_message,
        },
        "artifact": {
            "path": str(artifact_path),
            "exists": artifact_exists,
            "sha256": artifact_sha256,
            "retained_path": None if retained_artifact_path is None else str(retained_artifact_path),
            "binary_path": None if binary_artifact_path is None else str(binary_artifact_path),
            "binary_sha256": binary_artifact_sha256,
            "retained_binary_path": None if retained_binary_path is None else str(retained_binary_path),
            "binary_conversion": binary_conversion,
        },
    }
    _write_json(result_dir / "manifest.json", manifest)

    return WolfBootBuildResult(
        return_code=return_code,
        duration_seconds=duration_seconds,
        profile_id=profile_id,
        result_dir=result_dir,
        log_path=log_path,
        command=command,
        working_directory=working_directory,
        source_dir=source_dir,
        output_dir=output_dir,
        artifact_path=artifact_path,
        artifact_exists=artifact_exists,
        artifact_sha256=artifact_sha256,
        config_template_path=config_template_path,
        generated_config_path=generated_config_path,
        config_applied=config_applied,
        keytools_mingw_stdio_patch_enabled=keytools_mingw_stdio_patch_enabled,
        keytools_mingw_stdio_patch_applied=keytools_mingw_stdio_patch_applied,
        keytools_makefile_path=keytools_makefile_path,
        stm32l4_hal_conf_pwr_patch_enabled=stm32l4_hal_conf_pwr_patch_enabled,
        stm32l4_hal_conf_pwr_patch_applied=stm32l4_hal_conf_pwr_patch_applied,
        stm32l4_hal_conf_path=stm32l4_hal_conf_path,
        boot_timing_instrumentation_patch_enabled=boot_timing_instrumentation_patch_enabled,
        boot_timing_instrumentation_patch_applied=boot_timing_instrumentation_patch_applied,
        boot_timing_image_path=boot_timing_image_path,
        boot_timing_hal_path=boot_timing_hal_path,
        retained_artifact_path=retained_artifact_path,
        signing_key_path=signing_key_path,
        wolfboot_private_key_path=wolfboot_private_key_path,
        signing_key_sha256=signing_key_sha256,
        wolfboot_private_key_sha256=wolfboot_private_key_sha256,
        key_consistency_status=key_consistency_status,
        key_consistency_message=key_consistency_message,
        execution=execution,
        failure_reason=failure_reason,
    )
