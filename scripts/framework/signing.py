"""Application image signing helpers for wolfBoot experiments.

This module implements a local, explicit application-signing workflow. It can
invoke a configured key-generation command when a local private key is missing,
then invoke a configured signing command for a relocated application image and
record signing evidence. It does not flash hardware, open UART devices, use SSH,
or commit/copy private signing keys.
"""

from __future__ import annotations

import json
import os
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

MISSING_INPUT_IMAGE_RETURN_CODE = 30
SIGNED_IMAGE_MISSING_RETURN_CODE = 31
SIGNING_PROFILE_ERROR_RETURN_CODE = 32
SIGNING_TOOL_MISSING_RETURN_CODE = 33
PRIVATE_KEY_MISSING_RETURN_CODE = 34
KEYGEN_TOOL_MISSING_RETURN_CODE = 35
BINARY_CONVERSION_TOOL_MISSING_RETURN_CODE = 36
SIGNING_COMMAND_TIMEOUT_RETURN_CODE = 37
DEFAULT_SIGNING_COMMAND_TIMEOUT_SECONDS = 30
DEFAULT_SIGNING_RESULTS_SUBDIR = "signing"
DEFAULT_SIGNING_LOG_NAME = "signing.log"
DEFAULT_RETAINED_SIGNED_IMAGE_NAME = "application_signed.bin"


@dataclass(frozen=True)
class SigningCommandExecution:
    """Captured output from one local signing-related command."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class ApplicationSigningResult:
    """Captured result from a configured application-signing profile."""

    return_code: int
    duration_seconds: float
    profile_id: str
    result_dir: Path
    log_path: Path
    input_image_path: Path
    signed_image_path: Path
    private_key_path: Path
    private_key_existed_before: bool
    private_key_present_after: bool
    keygen_enabled: bool
    binary_conversion_enabled: bool
    binary_conversion_execution: SigningCommandExecution | None
    keygen_execution: SigningCommandExecution | None
    sign_execution: SigningCommandExecution | None
    input_image_sha256: str | None
    signed_image_sha256: str | None
    signed_image_size_bytes: int | None
    signature_algorithm: str
    signature_size_bytes: int | None
    image_version: str
    retained_signed_image_path: Path | None
    failure_reason: str | None = None


SigningRunner = Callable[[list[str], Path, str | None], SigningCommandExecution]


class ApplicationSigningProfileError(ValueError):
    """Raised when an application-signing profile is incomplete or invalid."""


def _safe_id_component(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("_.-")
    if not safe:
        raise ApplicationSigningProfileError("application signing profile id must contain at least one safe character")
    return safe


def _required(profile: dict[str, Any], dotted_path: str) -> Any:
    current: Any = profile
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ApplicationSigningProfileError(
                f"application signing profile missing required field: {dotted_path}"
            )
        current = current[part]
    if current is None or current == "":
        raise ApplicationSigningProfileError(
            f"application signing profile has empty required field: {dotted_path}"
        )
    return current


def _optional_bool(profile: dict[str, Any], dotted_path: str) -> bool:
    current: Any = profile
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current is True or str(current).strip().lower() in {"true", "yes", "1", "on"}


def _optional_str(profile: dict[str, Any], dotted_path: str) -> str | None:
    current: Any = profile
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    if current is None or current == "":
        return None
    return str(current)


def validate_application_signing_profile(profile: dict[str, Any]) -> None:
    """Validate the minimum schema for an application-signing profile."""

    required_fields = [
        "id",
        "description",
        "input_image",
        "signed_image",
        "signature_algorithm",
        "private_key",
        "image_version",
        "sign.command",
    ]

    for field in required_fields:
        _required(profile, field)

    algorithm = str(_required(profile, "signature_algorithm"))
    if algorithm != "ecdsa_p256":
        raise ApplicationSigningProfileError(
            "Phase 10g supports only signature_algorithm: ecdsa_p256"
        )

    sign_config = profile.get("sign")
    if not isinstance(sign_config, dict):
        raise ApplicationSigningProfileError("application signing profile sign field must be a mapping")

    keygen_config = profile.get("keygen", {})
    if keygen_config is not None and not isinstance(keygen_config, dict):
        raise ApplicationSigningProfileError("application signing profile keygen field must be a mapping")

    binary_conversion_config = profile.get("binary_conversion", {})
    if binary_conversion_config is not None and not isinstance(binary_conversion_config, dict):
        raise ApplicationSigningProfileError("application signing profile binary_conversion field must be a mapping")

    if _optional_bool(profile, "keygen.enabled") and not _optional_str(profile, "keygen.command"):
        raise ApplicationSigningProfileError(
            "application signing profile keygen.command is required when keygen.enabled is true"
        )

    if _optional_bool(profile, "binary_conversion.enabled"):
        if not _optional_str(profile, "input_elf"):
            raise ApplicationSigningProfileError(
                "application signing profile input_elf is required when binary_conversion.enabled is true"
            )
        if not _optional_str(profile, "binary_conversion.command"):
            raise ApplicationSigningProfileError(
                "application signing profile binary_conversion.command is required when binary_conversion.enabled is true"
            )


def _format_context(profile: dict[str, Any], repo_root: Path) -> dict[str, str]:
    return {
        "repo_root": str(repo_root),
        "input_image": str(repo_root / str(profile["input_image"])),
        "input_elf": str(repo_root / str(profile.get("input_elf", ""))),
        "signed_image": str(repo_root / str(profile["signed_image"])),
        "private_key": str(repo_root / str(profile["private_key"])),
        "image_version": str(profile["image_version"]),
        "signature_algorithm": str(profile["signature_algorithm"]),
    }


def _format_command(command: str, args: str | None, context: dict[str, str]) -> list[str]:
    rendered = command.format(**context)
    if args:
        rendered = f"{rendered} {args.format(**context)}"
    # Use posix=False so Windows absolute paths rendered into command arguments
    # keep backslashes. With the default POSIX lexer, a path such as
    # C:\Users\... is treated as containing escape sequences and becomes
    # C:Users..., which breaks signing/keygen commands on Windows.
    parsed = shlex.split(rendered, posix=False)
    if not parsed:
        raise ApplicationSigningProfileError("configured command produced an empty command")
    return parsed


def construct_keygen_command(profile: dict[str, Any], repo_root: Path | str) -> list[str] | None:
    """Construct the configured key-generation command, or ``None`` when disabled."""

    validate_application_signing_profile(profile)
    if not _optional_bool(profile, "keygen.enabled"):
        return None

    context = _format_context(profile, Path(repo_root))
    return _format_command(
        str(_required(profile, "keygen.command")),
        _optional_str(profile, "keygen.args"),
        context,
    )


def construct_binary_conversion_command(profile: dict[str, Any], repo_root: Path | str) -> list[str] | None:
    """Construct the configured ELF-to-BIN conversion command, or ``None`` when disabled."""

    validate_application_signing_profile(profile)
    if not _optional_bool(profile, "binary_conversion.enabled"):
        return None

    context = _format_context(profile, Path(repo_root))
    return _format_command(
        str(_required(profile, "binary_conversion.command")),
        _optional_str(profile, "binary_conversion.args"),
        context,
    )


def construct_signing_command(profile: dict[str, Any], repo_root: Path | str) -> list[str]:
    """Construct the configured application-signing command."""

    validate_application_signing_profile(profile)
    context = _format_context(profile, Path(repo_root))
    return _format_command(
        str(_required(profile, "sign.command")),
        _optional_str(profile, "sign.args"),
        context,
    )


def _section_working_dir(profile: dict[str, Any], section: str, repo_root: Path) -> Path:
    """Return the configured working directory for one signing-related command."""

    configured = _optional_str(profile, f"{section}.working_dir")
    if configured is None:
        return repo_root
    path = Path(configured)
    if path.is_absolute():
        return path
    return repo_root / path


def _section_stdin(profile: dict[str, Any], section: str) -> str | None:
    """Return configured stdin text for one signing-related command."""

    configured = _optional_str(profile, f"{section}.stdin")
    if configured is None:
        return None
    return configured.replace("\\n", "\n")


def _executable_extensions() -> list[str]:
    """Return executable suffixes to try for local command paths."""

    extensions = [""]
    if os.name == "nt":
        pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        extensions.extend(ext.lower() for ext in pathext.split(";") if ext)
        extensions.extend(ext.upper() for ext in pathext.split(";") if ext)
    else:
        extensions.append(".exe")

    unique: list[str] = []
    for extension in extensions:
        if extension not in unique:
            unique.append(extension)
    return unique


def _resolve_command_for_cwd(command: list[str], cwd: Path) -> list[str]:
    """Resolve local relative executables before invoking ``subprocess``.

    wolfBoot host keytools are built under ``tools/wolfboot/tools/keytools``.
    On Windows they are produced as ``.exe`` files, and ``subprocess`` does not
    reliably append ``PATHEXT`` for relative paths containing path separators.
    Resolve those configured relative tool paths against the command working
    directory while leaving PATH-based tools, such as ``arm-none-eabi-objcopy``,
    unchanged.
    """

    if not command:
        return command

    executable = command[0]
    if any(separator in executable for separator in ("/", "\\")) or Path(executable).is_absolute():
        base = Path(executable)
        if not base.is_absolute():
            base = cwd / base
        candidates = [base]
        if base.suffix == "":
            candidates.extend(Path(str(base) + extension) for extension in _executable_extensions() if extension)
        for candidate in candidates:
            if candidate.is_file():
                return [str(candidate), *command[1:]]

    return command


def _timeout_output(value: str | bytes | None) -> str:
    """Normalize subprocess timeout output to text for evidence logs."""

    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def default_signing_runner(command: list[str], cwd: Path, stdin_text: str | None = None) -> SigningCommandExecution:
    """Run a signing-related command and capture stdout, stderr, and timing."""

    resolved_command = _resolve_command_for_cwd(command, cwd)
    start = perf_counter()
    try:
        run_kwargs: dict[str, Any] = {
            "cwd": cwd,
            "text": True,
            "capture_output": True,
            "check": False,
            "timeout": DEFAULT_SIGNING_COMMAND_TIMEOUT_SECONDS,
        }
        if stdin_text is None:
            run_kwargs["stdin"] = subprocess.DEVNULL
        else:
            run_kwargs["input"] = stdin_text
        completed = subprocess.run(resolved_command, **run_kwargs)
    except subprocess.TimeoutExpired as exc:
        duration_seconds = perf_counter() - start
        stdout = _timeout_output(exc.stdout)
        stderr = _timeout_output(exc.stderr)
        timeout_message = (
            f"application signing command timed out after "
            f"{DEFAULT_SIGNING_COMMAND_TIMEOUT_SECONDS} seconds"
        )
        if stderr:
            stderr = f"{stderr}\n{timeout_message}"
        else:
            stderr = timeout_message
        return SigningCommandExecution(
            command=resolved_command,
            return_code=SIGNING_COMMAND_TIMEOUT_RETURN_CODE,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration_seconds,
        )
    return SigningCommandExecution(
        command=resolved_command,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=perf_counter() - start,
    )


def create_signing_result_dir(
    profile_id: str,
    results_root: Path | str = "results",
    timestamp: datetime | None = None,
) -> Path:
    """Create a result directory for one application-signing attempt."""

    current_timestamp = timestamp or datetime.now().astimezone()
    base = Path(results_root) / DEFAULT_SIGNING_RESULTS_SUBDIR
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


def _display_command(command: list[str] | None) -> str:
    if command is None:
        return "not run"
    return " ".join(shlex.quote(part) for part in command)


def _write_log(
    *,
    log_path: Path,
    profile: dict[str, Any],
    repo_root: Path,
    input_image_path: Path,
    input_elf_path: Path | None,
    signed_image_path: Path,
    private_key_path: Path,
    private_key_existed_before: bool,
    private_key_present_after: bool,
    keygen_enabled: bool,
    binary_conversion_enabled: bool,
    binary_conversion_execution: SigningCommandExecution | None,
    binary_conversion_working_dir: Path,
    keygen_execution: SigningCommandExecution | None,
    keygen_working_dir: Path,
    sign_execution: SigningCommandExecution | None,
    sign_working_dir: Path,
    input_image_sha256: str | None,
    signed_image_sha256: str | None,
    signed_image_size_bytes: int | None,
    retained_signed_image_path: Path | None,
    return_code: int,
    duration_seconds: float,
    failure_reason: str | None,
) -> None:
    lines = [
        "Application signing log",
        "=======================",
        f"Timestamp: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Profile ID: {profile.get('id')}",
        f"Repository root: {repo_root}",
        f"Input image path: {input_image_path}",
        f"Input ELF path: {input_elf_path if input_elf_path is not None else 'unconfigured'}",
        f"Input image SHA-256: {input_image_sha256 if input_image_sha256 is not None else 'unavailable'}",
        f"Signed image path: {signed_image_path}",
        f"Signed image SHA-256: {signed_image_sha256 if signed_image_sha256 is not None else 'unavailable'}",
        f"Signed image size bytes: {signed_image_size_bytes if signed_image_size_bytes is not None else 'unavailable'}",
        f"Retained signed image path: {retained_signed_image_path if retained_signed_image_path is not None else 'unavailable'}",
        f"Signature algorithm: {profile.get('signature_algorithm')}",
        f"Signature size bytes: {profile.get('signature_size_bytes', 'unavailable')}",
        f"Image version: {profile.get('image_version')}",
        f"Private key path: {private_key_path}",
        f"Private key existed before command: {str(private_key_existed_before).lower()}",
        f"Private key present after command: {str(private_key_present_after).lower()}",
        f"Key generation enabled: {str(keygen_enabled).lower()}",
        f"Binary conversion enabled: {str(binary_conversion_enabled).lower()}",
        f"Binary conversion working directory: {binary_conversion_working_dir}",
        f"Binary conversion command: {_display_command(None if binary_conversion_execution is None else binary_conversion_execution.command)}",
        f"Key generation working directory: {keygen_working_dir}",
        f"Key generation command: {_display_command(None if keygen_execution is None else keygen_execution.command)}",
        f"Signing working directory: {sign_working_dir}",
        f"Signing command: {_display_command(None if sign_execution is None else sign_execution.command)}",
        f"Final return code: {return_code}",
        f"Total duration seconds: {duration_seconds:.3f}",
        "Private signing keys are local-only evidence inputs and are not copied into the result directory.",
    ]

    if failure_reason is not None:
        lines.extend(["", "Failure reason", "--------------", failure_reason])

    for label, execution in (("Binary conversion command output", binary_conversion_execution), ("Key generation command output", keygen_execution), ("Signing command output", sign_execution)):
        if execution is None:
            continue
        lines.extend(
            [
                "",
                label,
                "-" * len(label),
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


def _profile_error_result(
    *,
    profile: dict[str, Any],
    repo_root: Path,
    results_root: Path | str,
    timestamp: datetime | None,
    start: float,
    failure_reason: str,
) -> ApplicationSigningResult:
    profile_id = str(profile.get("id", "invalid_signing_profile"))
    result_dir = create_signing_result_dir(profile_id, results_root, timestamp)
    log_path = result_dir / DEFAULT_SIGNING_LOG_NAME
    duration_seconds = perf_counter() - start
    dummy_path = repo_root
    _write_log(
        log_path=log_path,
        profile=profile,
        repo_root=repo_root,
        input_image_path=dummy_path,
        input_elf_path=None,
        signed_image_path=dummy_path,
        private_key_path=dummy_path,
        private_key_existed_before=False,
        private_key_present_after=False,
        keygen_enabled=False,
        binary_conversion_enabled=False,
        binary_conversion_execution=None,
        binary_conversion_working_dir=repo_root,
        keygen_execution=None,
        keygen_working_dir=repo_root,
        sign_execution=None,
        sign_working_dir=repo_root,
        input_image_sha256=None,
        signed_image_sha256=None,
        signed_image_size_bytes=None,
        retained_signed_image_path=None,
        return_code=SIGNING_PROFILE_ERROR_RETURN_CODE,
        duration_seconds=duration_seconds,
        failure_reason=failure_reason,
    )
    _write_json(
        result_dir / "manifest.json",
        {
            "record_type": "application_signing",
            "schema_version": 1,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "profile": profile_id,
            "result": "application_signing_failed",
            "signing": {
                "return_code": SIGNING_PROFILE_ERROR_RETURN_CODE,
                "duration_seconds": round(duration_seconds, 3),
                "log": DEFAULT_SIGNING_LOG_NAME,
                "failure_reason": failure_reason,
            },
        },
    )
    return ApplicationSigningResult(
        return_code=SIGNING_PROFILE_ERROR_RETURN_CODE,
        duration_seconds=duration_seconds,
        profile_id=profile_id,
        result_dir=result_dir,
        log_path=log_path,
        input_image_path=dummy_path,
        signed_image_path=dummy_path,
        private_key_path=dummy_path,
        private_key_existed_before=False,
        private_key_present_after=False,
        keygen_enabled=False,
        binary_conversion_enabled=False,
        binary_conversion_execution=None,
        keygen_execution=None,
        sign_execution=None,
        input_image_sha256=None,
        signed_image_sha256=None,
        signed_image_size_bytes=None,
        signature_algorithm=str(profile.get("signature_algorithm", "unknown")),
        signature_size_bytes=None,
        image_version=str(profile.get("image_version", "unknown")),
        retained_signed_image_path=None,
        failure_reason=failure_reason,
    )


def execute_application_signing(
    *,
    profile: dict[str, Any],
    repo_root: Path | str,
    results_root: Path | str = "results",
    runner: SigningRunner = default_signing_runner,
    timestamp: datetime | None = None,
) -> ApplicationSigningResult:
    """Execute a configured local application-signing workflow and record evidence."""

    repo_root_path = Path(repo_root)
    start = perf_counter()

    try:
        validate_application_signing_profile(profile)
        profile_id = str(profile["id"])
        keygen_command = construct_keygen_command(profile, repo_root_path)
        binary_conversion_command = construct_binary_conversion_command(profile, repo_root_path)
        signing_command = construct_signing_command(profile, repo_root_path)
        keygen_working_dir = _section_working_dir(profile, "keygen", repo_root_path)
        keygen_stdin = _section_stdin(profile, "keygen")
        binary_conversion_working_dir = _section_working_dir(profile, "binary_conversion", repo_root_path)
        binary_conversion_stdin = _section_stdin(profile, "binary_conversion")
        sign_working_dir = _section_working_dir(profile, "sign", repo_root_path)
        sign_stdin = _section_stdin(profile, "sign")
    except ApplicationSigningProfileError as exc:
        return _profile_error_result(
            profile=profile,
            repo_root=repo_root_path,
            results_root=results_root,
            timestamp=timestamp,
            start=start,
            failure_reason=str(exc),
        )

    result_dir = create_signing_result_dir(profile_id, results_root, timestamp)
    log_path = result_dir / DEFAULT_SIGNING_LOG_NAME
    input_image_path = repo_root_path / str(profile["input_image"])
    input_elf_config = _optional_str(profile, "input_elf")
    input_elf_path = None if input_elf_config is None else repo_root_path / input_elf_config
    signed_image_path = repo_root_path / str(profile["signed_image"])
    private_key_path = repo_root_path / str(profile["private_key"])
    keygen_enabled = _optional_bool(profile, "keygen.enabled")
    binary_conversion_enabled = _optional_bool(profile, "binary_conversion.enabled")
    private_key_existed_before = private_key_path.is_file()
    binary_conversion_execution: SigningCommandExecution | None = None
    keygen_execution: SigningCommandExecution | None = None
    sign_execution: SigningCommandExecution | None = None
    retained_signed_image_path: Path | None = None
    input_image_sha256: str | None = None
    signed_image_sha256: str | None = None
    signed_image_size_bytes: int | None = None
    return_code = 0
    failure_reason: str | None = None

    if not input_image_path.is_file() and binary_conversion_enabled:
        if input_elf_path is None or not input_elf_path.is_file():
            return_code = MISSING_INPUT_IMAGE_RETURN_CODE
            failure_reason = (
                "Configured relocated application BIN is absent and the configured ELF input for "
                f"binary conversion does not exist: {input_elf_path}"
            )
        else:
            input_image_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                binary_conversion_execution = runner(binary_conversion_command or [], binary_conversion_working_dir, binary_conversion_stdin)
                return_code = binary_conversion_execution.return_code
            except FileNotFoundError as exc:
                missing_executable = binary_conversion_command[0] if binary_conversion_command else "configured binary-conversion tool"
                return_code = BINARY_CONVERSION_TOOL_MISSING_RETURN_CODE
                failure_reason = (
                    "application signing binary-conversion command could not be started because "
                    f"the executable was not found: {missing_executable}"
                )
                binary_conversion_execution = SigningCommandExecution(
                    command=binary_conversion_command or [],
                    return_code=return_code,
                    stdout="",
                    stderr=f"{failure_reason}\n{exc}",
                    duration_seconds=perf_counter() - start,
                )
            if return_code != 0 and failure_reason is None:
                failure_reason = f"application signing binary-conversion command failed with return code {return_code}."

    if return_code == 0 and not input_image_path.is_file():
        return_code = MISSING_INPUT_IMAGE_RETURN_CODE
        failure_reason = f"Configured relocated application image does not exist: {input_image_path}"
    elif return_code == 0:
        input_image_sha256 = calculate_file_sha256(input_image_path)

    if return_code == 0 and not private_key_path.is_file():
        if keygen_enabled:
            private_key_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                keygen_execution = runner(keygen_command or [], keygen_working_dir, keygen_stdin)
                return_code = keygen_execution.return_code
            except FileNotFoundError as exc:
                missing_executable = keygen_command[0] if keygen_command else "configured key-generation tool"
                return_code = KEYGEN_TOOL_MISSING_RETURN_CODE
                failure_reason = (
                    "application signing key-generation command could not be started because "
                    f"the executable was not found: {missing_executable}"
                )
                keygen_execution = SigningCommandExecution(
                    command=keygen_command or [],
                    return_code=return_code,
                    stdout="",
                    stderr=f"{failure_reason}\n{exc}",
                    duration_seconds=perf_counter() - start,
                )
            if return_code != 0 and failure_reason is None:
                failure_reason = f"application signing key-generation command failed with return code {return_code}."
        else:
            return_code = PRIVATE_KEY_MISSING_RETURN_CODE
            failure_reason = f"Configured private signing key does not exist and key generation is disabled: {private_key_path}"

    if return_code == 0 and not private_key_path.is_file():
        return_code = PRIVATE_KEY_MISSING_RETURN_CODE
        failure_reason = f"Configured private signing key is still absent after key generation: {private_key_path}"

    if return_code == 0:
        signed_image_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            sign_execution = runner(signing_command, sign_working_dir, sign_stdin)
            return_code = sign_execution.return_code
        except FileNotFoundError as exc:
            missing_executable = signing_command[0] if signing_command else "configured signing tool"
            return_code = SIGNING_TOOL_MISSING_RETURN_CODE
            failure_reason = (
                "application signing command could not be started because the executable was not found: "
                f"{missing_executable}"
            )
            sign_execution = SigningCommandExecution(
                command=signing_command,
                return_code=return_code,
                stdout="",
                stderr=f"{failure_reason}\n{exc}",
                duration_seconds=perf_counter() - start,
            )
        if return_code != 0 and failure_reason is None:
            failure_reason = f"application signing command failed with return code {return_code}."

    if return_code == 0:
        if signed_image_path.is_file():
            signed_image_sha256 = calculate_file_sha256(signed_image_path)
            signed_image_size_bytes = signed_image_path.stat().st_size
            retained_name = str(profile.get("retained_signed_image", DEFAULT_RETAINED_SIGNED_IMAGE_NAME))
            retained_signed_image_path = copy_artifact_to_result(
                signed_image_path,
                result_dir,
                retained_name,
            )
        else:
            return_code = SIGNED_IMAGE_MISSING_RETURN_CODE
            failure_reason = (
                "application signing command returned success, but the configured signed image was not found: "
                f"{signed_image_path}"
            )

    duration_seconds = perf_counter() - start
    private_key_present_after = private_key_path.is_file()
    if signed_image_path.is_file() and signed_image_sha256 is None:
        signed_image_sha256 = calculate_file_sha256(signed_image_path)
        signed_image_size_bytes = signed_image_path.stat().st_size

    signature_size_value = profile.get("signature_size_bytes")
    signature_size_bytes = int(signature_size_value) if signature_size_value not in (None, "") else None

    _write_log(
        log_path=log_path,
        profile=profile,
        repo_root=repo_root_path,
        input_image_path=input_image_path,
        input_elf_path=input_elf_path,
        signed_image_path=signed_image_path,
        private_key_path=private_key_path,
        private_key_existed_before=private_key_existed_before,
        private_key_present_after=private_key_present_after,
        keygen_enabled=keygen_enabled,
        binary_conversion_enabled=binary_conversion_enabled,
        binary_conversion_execution=binary_conversion_execution,
        binary_conversion_working_dir=binary_conversion_working_dir,
        keygen_execution=keygen_execution,
        keygen_working_dir=keygen_working_dir,
        sign_execution=sign_execution,
        sign_working_dir=sign_working_dir,
        input_image_sha256=input_image_sha256,
        signed_image_sha256=signed_image_sha256,
        signed_image_size_bytes=signed_image_size_bytes,
        retained_signed_image_path=retained_signed_image_path,
        return_code=return_code,
        duration_seconds=duration_seconds,
        failure_reason=failure_reason,
    )

    _write_json(
        result_dir / "manifest.json",
        {
            "record_type": "application_signing",
            "schema_version": 1,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "profile": profile_id,
            "result": "application_signing_passed" if return_code == 0 else "application_signing_failed",
            "signing": {
                "profile_id": profile_id,
                "description": profile.get("description"),
                "return_code": return_code,
                "duration_seconds": round(duration_seconds, 3),
                "log": DEFAULT_SIGNING_LOG_NAME,
                "failure_reason": failure_reason,
                "signature_algorithm": profile.get("signature_algorithm"),
                "signature_size_bytes": signature_size_bytes,
                "image_version": str(profile.get("image_version")),
                "input_elf": None if input_elf_path is None else str(input_elf_path),
                "input_image": str(input_image_path),
                "input_image_sha256": input_image_sha256,
                "binary_conversion_enabled": binary_conversion_enabled,
                "binary_conversion_working_dir": str(binary_conversion_working_dir),
                "binary_conversion_return_code": None if binary_conversion_execution is None else binary_conversion_execution.return_code,
                "signed_image": str(signed_image_path),
                "signed_image_sha256": signed_image_sha256,
                "signed_image_size_bytes": signed_image_size_bytes,
                "retained_signed_image": None if retained_signed_image_path is None else str(retained_signed_image_path),
                "private_key_path": str(private_key_path),
                "private_key_existed_before": private_key_existed_before,
                "private_key_present_after": private_key_present_after,
                "keygen_enabled": keygen_enabled,
                "keygen_working_dir": str(keygen_working_dir),
                "keygen_return_code": None if keygen_execution is None else keygen_execution.return_code,
                "sign_working_dir": str(sign_working_dir),
                "sign_return_code": None if sign_execution is None else sign_execution.return_code,
                "key_material_copied_to_results": False,
            },
        },
    )

    return ApplicationSigningResult(
        return_code=return_code,
        duration_seconds=duration_seconds,
        profile_id=profile_id,
        result_dir=result_dir,
        log_path=log_path,
        input_image_path=input_image_path,
        signed_image_path=signed_image_path,
        private_key_path=private_key_path,
        private_key_existed_before=private_key_existed_before,
        private_key_present_after=private_key_present_after,
        keygen_enabled=keygen_enabled,
        binary_conversion_enabled=binary_conversion_enabled,
        binary_conversion_execution=binary_conversion_execution,
        keygen_execution=keygen_execution,
        sign_execution=sign_execution,
        input_image_sha256=input_image_sha256,
        signed_image_sha256=signed_image_sha256,
        signed_image_size_bytes=signed_image_size_bytes,
        signature_algorithm=str(profile.get("signature_algorithm")),
        signature_size_bytes=signature_size_bytes,
        image_version=str(profile.get("image_version")),
        retained_signed_image_path=retained_signed_image_path,
        failure_reason=failure_reason,
    )
