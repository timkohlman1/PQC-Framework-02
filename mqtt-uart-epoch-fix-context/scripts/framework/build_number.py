"""Local build-number tracking for experiment result manifests.

The build number is deliberately simple local state stored in ``.build_number``
at the repository root. It performs no hardware, network, UART, SSH, Git, or
toolchain actions.
"""

from __future__ import annotations

from pathlib import Path

BUILD_NUMBER_FILENAME = ".build_number"


class BuildNumberError(Exception):
    """Raised when the build-number state cannot be read or updated safely."""


def _parse_build_number(raw_value: str, path: Path) -> int:
    value = raw_value.strip()

    if value == "":
        return 0

    try:
        number = int(value)
    except ValueError as exc:
        raise BuildNumberError(
            f"Build number file contains a non-integer value: {path}"
        ) from exc

    if number < 0:
        raise BuildNumberError(
            f"Build number file contains a negative value: {path}"
        )

    return number


def reserve_next_build_number(repo_root: Path | str) -> int:
    """Increment and return the next local build number.

    If ``.build_number`` does not exist, build number ``1`` is assigned. The
    updated file contains only the latest integer and a trailing newline.
    """

    repo_root_path = Path(repo_root)
    build_number_path = repo_root_path / BUILD_NUMBER_FILENAME

    if build_number_path.exists():
        if not build_number_path.is_file():
            raise BuildNumberError(
                f"Build number path exists but is not a file: {build_number_path}"
            )
        current_number = _parse_build_number(
            build_number_path.read_text(encoding="utf-8"),
            build_number_path,
        )
    else:
        current_number = 0

    next_number = current_number + 1
    build_number_path.write_text(f"{next_number}\n", encoding="utf-8")
    return next_number
