"""wolfBoot build-profile helpers.

This module runs a configured local wolfBoot build and records build evidence.
It does not flash hardware, open UART devices, use SSH, sign application images,
or copy private signing keys into result directories.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from framework.artifacts import calculate_file_sha256, copy_artifact_to_result
from framework.generated_state import (
    build_identity,
    detect_execution_identity,
    key_tuple_fingerprint,
    preflight_generated_state,
    record_generated_state_success,
)
from framework.fingerprint import (
    FingerprintInputError,
    calculate_existing_inputs_fingerprint,
    default_wolfboot_fingerprint_inputs,
)

MISSING_SOURCE_RETURN_CODE = 20
WOLFBOOT_BUILD_ARTIFACT_MISSING_RETURN_CODE = 21
PROFILE_ERROR_RETURN_CODE = 22
WOLFBOOT_BUILD_TOOL_MISSING_RETURN_CODE = 23
DEFAULT_WOLFBOOT_RESULTS_SUBDIR = "wolfboot-builds"
DEFAULT_WOLFBOOT_LOG_NAME = "wolfboot_build.log"
MINGW_KEYTOOLS_STDIO_DEFINE = "-D__USE_MINGW_ANSI_STDIO=1"
KEYTOOLS_MAKEFILE_RELATIVE_PATH = Path("tools/keytools/Makefile")
STM32L4_HAL_CONF_RELATIVE_PATH = Path("hal/stm32l4xx_hal_conf.h")
STM32L4_HAL_SOURCE_RELATIVE_PATH = Path("hal/stm32l4.c")
WOLFBOOT_IMAGE_SOURCE_RELATIVE_PATH = Path("src/image.c")
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
    if algorithm not in {"ecdsa_p256", "ed25519", "rsa2048", "ecc384", "ecc521", "ed448", "rsa3072", "rsa4096", "mldsa44", "mldsa65"}:
        raise WolfBootBuildProfileError(
            "wolfBoot build profile signature_algorithm must be ecdsa_p256, ed25519, rsa2048, ecc384, ecc521, ed448, rsa3072, rsa4096, mldsa44, or mldsa65"
        )


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
    """Temporarily instrument wolfBoot verification timing for STM32L4R5.

    Phase 10k needs wolfBoot to produce a concrete timing value. The earlier
    UART-in-wolfBoot approach was unreliable because the application UART path
    is already known-good while the bootloader's early USART state is not. This
    patch wraps wolfBoot's image-authenticity function with a Cortex-M DWT
    cycle-counter measurement and writes the measured value to a fixed RAM2
    mailbox. The relocated HAL application reads that mailbox after its UART is
    initialized and emits the framework-parsed line:

        wolfBoot verification cycles: <N> cycles
        wolfBoot clock sysclk_hz: <N>
        wolfBoot clock hclk_hz: <N>
        wolfBoot clock pclk1_hz: <N>
        wolfBoot clock pclk2_hz: <N>

    The wolfBoot source is restored after the build command runs.
    """

    if not _optional_profile_bool(profile, "build.boot_timing_instrumentation_patch"):
        return None, None, False, None, None

    image_path = source_dir / WOLFBOOT_IMAGE_SOURCE_RELATIVE_PATH
    if not image_path.is_file():
        raise WolfBootBuildProfileError(
            f"wolfBoot image source not found for boot timing patch: {image_path}"
        )

    original_image_text = image_path.read_text(encoding="utf-8")

    image_marker = "PQC_BOOT_TIMING_MAILBOX_MAGIC"
    image_already_patched = image_marker in original_image_text

    patched_image_text = original_image_text
    image_original_to_restore: str | None = original_image_text

    if not image_already_patched:
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
        wrapper = """\n#if defined(WOLFBOOT_PQC_BOOT_TIMING)
#ifndef WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR
#define WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR 0x10000000UL
#endif

#define PQC_BOOT_TIMING_DEMCR        (*(volatile uint32_t *)0xE000EDFCUL)
#define PQC_BOOT_TIMING_DWT_CTRL     (*(volatile uint32_t *)0xE0001000UL)
#define PQC_BOOT_TIMING_DWT_CYCCNT   (*(volatile uint32_t *)0xE0001004UL)
#define PQC_BOOT_TIMING_DEMCR_TRCENA (1UL << 24)
#define PQC_BOOT_TIMING_DWT_CYCCNTENA (1UL << 0)
#define PQC_BOOT_TIMING_MAILBOX_MAGIC 0x50514354UL
#define PQC_BOOT_TIMING_MAILBOX_VERSION 2UL
#define PQC_BOOT_STACK_SENTINEL 0xA5U
#define PQC_BOOT_STACK_SCAN_GUARD_BYTES 256U
#define PQC_BOOT_STACK_UNAVAILABLE 0xFFFFFFFFUL
#define PQC_BOOT_HSI_HZ 16000000UL
#define PQC_BOOT_MSI_HZ 4000000UL
#define PQC_BOOT_HSE_HZ 0UL
#define PQC_BOOT_RCC_BASE 0x40021000UL
#define PQC_BOOT_RCC_CFGR (*(volatile uint32_t *)(PQC_BOOT_RCC_BASE + 0x08UL))
#define PQC_BOOT_RCC_PLLCFGR (*(volatile uint32_t *)(PQC_BOOT_RCC_BASE + 0x0CUL))
#define PQC_BOOT_RCC_CFGR_SWS_MASK (0x3UL << 2)
#define PQC_BOOT_RCC_CFGR_SWS_MSI (0x0UL << 2)
#define PQC_BOOT_RCC_CFGR_SWS_HSI (0x1UL << 2)
#define PQC_BOOT_RCC_CFGR_SWS_HSE (0x2UL << 2)
#define PQC_BOOT_RCC_CFGR_SWS_PLL (0x3UL << 2)
#define PQC_BOOT_RCC_CFGR_HPRE_MASK (0xFUL << 4)
#define PQC_BOOT_RCC_CFGR_HPRE_POS 4U
#define PQC_BOOT_RCC_CFGR_PPRE1_MASK (0x7UL << 8)
#define PQC_BOOT_RCC_CFGR_PPRE1_POS 8U
#define PQC_BOOT_RCC_CFGR_PPRE2_MASK (0x7UL << 11)
#define PQC_BOOT_RCC_CFGR_PPRE2_POS 11U
#define PQC_BOOT_RCC_PLLCFGR_PLLSRC_MASK 0x3UL
#define PQC_BOOT_RCC_PLLCFGR_PLLSRC_MSI 0x1UL
#define PQC_BOOT_RCC_PLLCFGR_PLLSRC_HSI 0x2UL
#define PQC_BOOT_RCC_PLLCFGR_PLLSRC_HSE 0x3UL
#define PQC_BOOT_RCC_PLLCFGR_PLLM_MASK (0x7UL << 4)
#define PQC_BOOT_RCC_PLLCFGR_PLLM_POS 4U
#define PQC_BOOT_RCC_PLLCFGR_PLLN_MASK (0x7FUL << 8)
#define PQC_BOOT_RCC_PLLCFGR_PLLN_POS 8U
#define PQC_BOOT_RCC_PLLCFGR_PLLR_MASK (0x3UL << 25)
#define PQC_BOOT_RCC_PLLCFGR_PLLR_POS 25U

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
};

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
    switch (pllcfgr & PQC_BOOT_RCC_PLLCFGR_PLLSRC_MASK) {
        case PQC_BOOT_RCC_PLLCFGR_PLLSRC_MSI: return PQC_BOOT_MSI_HZ;
        case PQC_BOOT_RCC_PLLCFGR_PLLSRC_HSI: return PQC_BOOT_HSI_HZ;
        case PQC_BOOT_RCC_PLLCFGR_PLLSRC_HSE: return PQC_BOOT_HSE_HZ;
        default: return 0U;
    }
}

static uint32_t pqc_boot_reported_sysclk_hz(void)
{
    uint32_t cfgr = PQC_BOOT_RCC_CFGR;
    uint32_t sws = cfgr & PQC_BOOT_RCC_CFGR_SWS_MASK;
    if (sws == PQC_BOOT_RCC_CFGR_SWS_HSI) return PQC_BOOT_HSI_HZ;
    if (sws == PQC_BOOT_RCC_CFGR_SWS_MSI) return PQC_BOOT_MSI_HZ;
    if (sws == PQC_BOOT_RCC_CFGR_SWS_HSE) return PQC_BOOT_HSE_HZ;
    if (sws == PQC_BOOT_RCC_CFGR_SWS_PLL) {
        uint32_t pll = PQC_BOOT_RCC_PLLCFGR;
        uint32_t source_hz = pqc_boot_pll_source_hz(pll);
        uint32_t m = ((pll & PQC_BOOT_RCC_PLLCFGR_PLLM_MASK) >> PQC_BOOT_RCC_PLLCFGR_PLLM_POS) + 1U;
        uint32_t n = (pll & PQC_BOOT_RCC_PLLCFGR_PLLN_MASK) >> PQC_BOOT_RCC_PLLCFGR_PLLN_POS;
        uint32_t r = ((((pll & PQC_BOOT_RCC_PLLCFGR_PLLR_MASK) >> PQC_BOOT_RCC_PLLCFGR_PLLR_POS) + 1U) * 2U);
        if (source_hz == 0U || m == 0U || r == 0U) return 0U;
        return (uint32_t)((((uint64_t)source_hz / m) * n) / r);
    }
    return 0U;
}

static void pqc_boot_reported_clocks(uint32_t *sysclk_hz, uint32_t *hclk_hz, uint32_t *pclk1_hz, uint32_t *pclk2_hz)
{
    uint32_t cfgr = PQC_BOOT_RCC_CFGR;
    uint32_t sysclk = pqc_boot_reported_sysclk_hz();
    uint32_t hclk = sysclk / pqc_boot_decode_ahb_divider((cfgr & PQC_BOOT_RCC_CFGR_HPRE_MASK) >> PQC_BOOT_RCC_CFGR_HPRE_POS);
    *sysclk_hz = sysclk;
    *hclk_hz = hclk;
    *pclk1_hz = hclk / pqc_boot_decode_apb_divider((cfgr & PQC_BOOT_RCC_CFGR_PPRE1_MASK) >> PQC_BOOT_RCC_CFGR_PPRE1_POS);
    *pclk2_hz = hclk / pqc_boot_decode_apb_divider((cfgr & PQC_BOOT_RCC_CFGR_PPRE2_MASK) >> PQC_BOOT_RCC_CFGR_PPRE2_POS);
}

static void pqc_boot_timing_counter_start(uint32_t *start_cycles)
{
    PQC_BOOT_TIMING_DEMCR |= PQC_BOOT_TIMING_DEMCR_TRCENA;
    PQC_BOOT_TIMING_DWT_CYCCNT = 0U;
    PQC_BOOT_TIMING_DWT_CTRL |= PQC_BOOT_TIMING_DWT_CYCCNTENA;
    *start_cycles = PQC_BOOT_TIMING_DWT_CYCCNT;
}

static uint32_t pqc_boot_timing_counter_elapsed(uint32_t start_cycles)
{
    return PQC_BOOT_TIMING_DWT_CYCCNT - start_cycles;
}

static uintptr_t pqc_boot_current_stack_pointer(void)
{
    uintptr_t sp;
    __asm__ volatile ("mrs %0, msp" : "=r" (sp));
    return sp;
}

static uint8_t *pqc_boot_stack_paint_start(void) { extern uint8_t _end; return &_end; }
static uint8_t *pqc_boot_stack_paint_end(void)
{
    uintptr_t sp = pqc_boot_current_stack_pointer();
    if (sp <= PQC_BOOT_STACK_SCAN_GUARD_BYTES) return pqc_boot_stack_paint_start();
    return (uint8_t *)(sp - PQC_BOOT_STACK_SCAN_GUARD_BYTES);
}
static void pqc_boot_stack_paint(uint8_t *start, uint8_t *end)
{
    uint8_t *cursor; if (end <= start) return;
    for (cursor = start; cursor < end; cursor++) *cursor = PQC_BOOT_STACK_SENTINEL;
}
static uint32_t pqc_boot_stack_high_water(uint8_t *start, uint8_t *end)
{
    uint8_t *cursor; if (end <= start) return PQC_BOOT_STACK_UNAVAILABLE;
    for (cursor = start; cursor < end; cursor++) if (*cursor != PQC_BOOT_STACK_SENTINEL) return (uint32_t)(end - cursor);
    return 0U;
}

static void pqc_boot_timing_write_mailbox(uint32_t elapsed_cycles, int verification_result, uint32_t max_stack_used_bytes)
{
    volatile struct pqc_boot_timing_mailbox *mailbox =
        (volatile struct pqc_boot_timing_mailbox *)WOLFBOOT_PQC_BOOT_TIMING_MAILBOX_ADDR;
    uint32_t sysclk_hz, hclk_hz, pclk1_hz, pclk2_hz;
    pqc_boot_reported_clocks(&sysclk_hz, &hclk_hz, &pclk1_hz, &pclk2_hz);
    mailbox->magic = 0U;
    mailbox->version = PQC_BOOT_TIMING_MAILBOX_VERSION;
    mailbox->elapsed_cycles = elapsed_cycles;
    mailbox->verification_result = (uint32_t)verification_result;
    mailbox->max_stack_used_bytes = max_stack_used_bytes;
    mailbox->sysclk_hz = sysclk_hz;
    mailbox->hclk_hz = hclk_hz;
    mailbox->pclk1_hz = pclk1_hz;
    mailbox->pclk2_hz = pclk2_hz;
    mailbox->magic = PQC_BOOT_TIMING_MAILBOX_MAGIC;
}

int wolfBoot_verify_authenticity(struct wolfBoot_image *img)
{
    uint32_t start_cycles, elapsed_cycles, max_stack_used_bytes;
    uint8_t *stack_paint_start, *stack_paint_end;
    int ret;
    stack_paint_start = pqc_boot_stack_paint_start();
    stack_paint_end = pqc_boot_stack_paint_end();
    pqc_boot_stack_paint(stack_paint_start, stack_paint_end);
    pqc_boot_timing_counter_start(&start_cycles);
    ret = wolfBoot_verify_authenticity_impl(img);
    elapsed_cycles = pqc_boot_timing_counter_elapsed(start_cycles);
    max_stack_used_bytes = pqc_boot_stack_high_water(stack_paint_start, stack_paint_end);
    pqc_boot_timing_write_mailbox(elapsed_cycles, ret, max_stack_used_bytes);
    return ret;
}
#endif
"""
        if wrapper_marker not in patched_image_text:
            raise WolfBootBuildProfileError(
                "Could not locate safe insertion point after wolfBoot_verify_authenticity()"
            )
        patched_image_text = patched_image_text.replace(
            wrapper_marker,
            f"{wrapper}\n{wrapper_marker}",
            1,
        )
    else:
        image_original_to_restore = None

    if patched_image_text != original_image_text:
        image_path.write_text(patched_image_text, encoding="utf-8")

    return image_path, None, True, image_original_to_restore, None


def _copy_project_local_config(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    source_dir: Path,
) -> tuple[Path | None, Path | None, bool]:
    """Copy a repository-local wolfBoot config template into the local source tree.

    The generated file is intentionally placed inside the local wolfBoot working
    tree because upstream wolfBoot reads its normal build settings from
    ``.config``. The template remains tracked in this repository; the generated
    copy and all wolfBoot build outputs remain local developer state.
    """

    config_template = _optional_profile_path(profile, "build.config_template")
    generated_config = _optional_profile_path(profile, "build.generated_config")

    if config_template is None and generated_config is None:
        return None, None, False

    if config_template is None or generated_config is None:
        raise WolfBootBuildProfileError(
            "wolfBoot build profile must set both build.config_template and "
            "build.generated_config, or neither"
        )

    template_path = repo_root / config_template
    generated_path = repo_root / generated_config

    try:
        generated_path.relative_to(source_dir)
    except ValueError as exc:
        raise WolfBootBuildProfileError(
            "wolfBoot build.generated_config must be inside the configured source_dir"
        ) from exc

    if not template_path.is_file():
        raise WolfBootBuildProfileError(
            f"wolfBoot build config template not found: {template_path}"
        )

    generated_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_path, generated_path)
    return template_path, generated_path, True


def _remove_wolfboot_host_tool_outputs(source_dir: Path) -> list[Path]:
    """Remove generated wolfBoot host-tool outputs before a local build.

    wolfBoot builds several host utilities, including ``bin-assemble`` and
    signing/key-generation tools. In this project the wolfBoot submodule is
    often shared between the native Windows workflow and the Linux container
    through a bind mount. Stale object files and dependency files can otherwise
    carry host-specific paths, such as ``/workspace`` from a container run, into
    a native Windows build or vice versa. These files are generated build
    products, not source files or signing secrets, so removing them before the
    build is safe and keeps cross-host/container builds deterministic.
    """

    removed: list[Path] = []
    for pattern in WOLFBOOT_HOST_TOOL_OUTPUT_PATTERNS:
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
) -> str | None:
    if signing_key_path is None or wolfboot_private_key_path is None:
        return None
    if return_code != 0:
        return "wolfBoot build did not pass; canonical signing key was not updated from wolfBoot key material."
    if not wolfboot_private_key_path.is_file():
        return "wolfBoot private key was not found after build; canonical signing key could not be synchronized."
    signing_key_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(wolfboot_private_key_path, signing_key_path)
    return "Copied wolfBoot private key back to the configured canonical signing-key path after successful build."


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
            "requested_fingerprint_inputs": requested_inputs,
            "missing_fingerprint_inputs": missing_inputs,
            "limitations": str(exc),
        }
    return {
        "status": "available",
        "fingerprint": fingerprint.fingerprint,
        "fingerprint_algorithm": fingerprint.algorithm,
        "fingerprint_inputs": fingerprint.inputs,
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

    execution: WolfBootCommandExecution | None = None
    artifact_sha256: str | None = None
    retained_artifact_path: Path | None = None
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
                extra={"signature_algorithm": profile.get("signature_algorithm")},
            )
            generated_cleanup_paths = [
                path
                for pattern in WOLFBOOT_HOST_TOOL_OUTPUT_PATTERNS
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
                                if signing_artifact_error is not None:
                                    return_code = PROFILE_ERROR_RETURN_CODE
                                    failure_reason = signing_artifact_error
                                else:
                                    key_sync_before_build_message = _coordinate_wolfboot_signing_key_before_build(
                                        signing_key_path=signing_key_path,
                                        wolfboot_private_key_path=wolfboot_private_key_path,
                                    )
                                    execution = runner(command, working_directory)
                                    return_code = execution.return_code
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
                retained_artifact_path = copy_artifact_to_result(
                    artifact_path,
                    result_dir,
                    "wolfboot.elf",
                )
            else:
                return_code = WOLFBOOT_BUILD_ARTIFACT_MISSING_RETURN_CODE
                failure_reason = (
                    "wolfBoot build command returned success, but the configured artifact was not found: "
                    f"{artifact_path}"
                )
        elif failure_reason is None:
            failure_reason = f"wolfBoot build command failed with return code {return_code}."

    key_sync_after_build_message = _coordinate_wolfboot_signing_key_after_build(
        signing_key_path=signing_key_path,
        wolfboot_private_key_path=wolfboot_private_key_path,
        return_code=return_code,
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

    if return_code == 0 and wolfboot_state_identity is not None:
        record_generated_state_success(
            repo_root=repo_root_path,
            scope=f"wolfboot-{profile_id}",
            identity=wolfboot_state_identity,
            artifacts=[artifact_path],
            record_refs={"wolfboot_build_manifest": str(result_dir / "manifest.json")},
        )

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
            "key_material_copied_to_results": False,
            "fingerprint": fingerprint_evidence.get("fingerprint"),
            "fingerprint_algorithm": fingerprint_evidence.get("fingerprint_algorithm"),
            "fingerprint_inputs": fingerprint_evidence.get("fingerprint_inputs", []),
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
            "boot_timing_instrumentation_patch_enabled": boot_timing_instrumentation_patch_enabled,
            "boot_timing_instrumentation_patch_applied": boot_timing_instrumentation_patch_applied,
            "boot_timing_image_path": None if boot_timing_image_path is None else str(boot_timing_image_path),
            "boot_timing_hal_path": None if boot_timing_hal_path is None else str(boot_timing_hal_path),
        },
        "artifact": {
            "path": str(artifact_path),
            "exists": artifact_exists,
            "sha256": artifact_sha256,
            "retained_path": None if retained_artifact_path is None else str(retained_artifact_path),
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
