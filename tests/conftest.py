from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


DEFAULT_EXPERIMENT_CONFIG = "configs/experiments/baseline_direct_uart.yaml"
DEFAULT_HOST_CONFIG = "configs/hosts/gateway.yaml"
SSH_TIMEOUT_SECONDS = 5
COMMAND_TIMEOUT_SECONDS = 5


TEST_PHASE_UNIT = "unit"
TEST_PHASE_OTHER = "other"
TEST_PHASE_INTEGRATION = "integration"
TEST_PHASE_HARDWARE = "hardware"
TEST_PHASE_ORDER = {
    TEST_PHASE_UNIT: 0,
    TEST_PHASE_OTHER: 1,
    TEST_PHASE_INTEGRATION: 2,
    TEST_PHASE_HARDWARE: 3,
}
LOWER_TEST_PHASES = {
    TEST_PHASE_UNIT: (),
    TEST_PHASE_OTHER: (TEST_PHASE_UNIT,),
    TEST_PHASE_INTEGRATION: (TEST_PHASE_UNIT, TEST_PHASE_OTHER),
    TEST_PHASE_HARDWARE: (
        TEST_PHASE_UNIT,
        TEST_PHASE_OTHER,
        TEST_PHASE_INTEGRATION,
    ),
}
FAILED_TEST_PHASES_KEY = "pqc_failed_test_phases"
DURATION_MARK_EXPR_KEY = "pqc_duration_mark_expr"


def _normalised_nodeid(item: pytest.Item) -> str:
    return item.nodeid.replace("\\", "/")


def _test_phase(item: pytest.Item) -> str:
    nodeid = _normalised_nodeid(item)
    if nodeid.startswith("tests/hardware/") or item.get_closest_marker(TEST_PHASE_HARDWARE):
        return TEST_PHASE_HARDWARE
    if nodeid.startswith("tests/integration/") or item.get_closest_marker(TEST_PHASE_INTEGRATION):
        return TEST_PHASE_INTEGRATION
    if nodeid.startswith("tests/unit/"):
        return TEST_PHASE_UNIT
    return TEST_PHASE_OTHER


def _failed_test_phases(config: pytest.Config) -> set[str]:
    failed = getattr(config, FAILED_TEST_PHASES_KEY, None)
    if failed is None:
        failed = set()
        setattr(config, FAILED_TEST_PHASES_KEY, failed)
    return failed


@dataclass(frozen=True)
class CapabilityResult:
    name: str
    available: bool
    reason: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _run_probe(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout_seconds: int = COMMAND_TIMEOUT_SECONDS,
) -> CapabilityResult:
    name = " ".join(args)
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return CapabilityResult(name, False, f"command not found: {args[0]}")
    except subprocess.TimeoutExpired:
        return CapabilityResult(name, False, f"probe timed out after {timeout_seconds} seconds")

    if completed.returncode == 0:
        return CapabilityResult(name, True, "available")

    detail = (completed.stderr or completed.stdout or "").strip()
    if detail:
        return CapabilityResult(
            name,
            False,
            f"probe returned {completed.returncode}: {detail}",
        )
    return CapabilityResult(name, False, f"probe returned {completed.returncode}")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return _load_simple_yaml(path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def _load_simple_yaml(path: Path) -> dict[str, Any]:
    """Parse the small config subset used by these capability checks.

    This fallback avoids making pytest collection depend on PyYAML. It supports
    the simple nested key/value YAML currently used by configs/hosts/gateway.yaml.
    """

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')

        while stack and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]
        if value:
            parent[key] = value
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))

    return root


def _host_config() -> dict[str, Any]:
    path = _repo_root() / DEFAULT_HOST_CONFIG
    if not path.is_file():
        return {}
    return _load_yaml(path)


def _nested(config: dict[str, Any], *keys: str) -> str | None:
    current: Any = config
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if current is None:
        return None
    return str(current)


def _ssh_probe(host_alias: str, command: str) -> CapabilityResult:
    return _run_probe(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={SSH_TIMEOUT_SECONDS}",
            host_alias,
            command,
        ],
        cwd=_repo_root(),
        timeout_seconds=SSH_TIMEOUT_SECONDS + 2,
    )


class PqcCapabilityChecker:
    def __init__(self) -> None:
        self._cache: dict[str, CapabilityResult] = {}

    def check(self, name: str) -> CapabilityResult:
        if name not in self._cache:
            self._cache[name] = self._check_uncached(name)
        return self._cache[name]

    def _check_uncached(self, name: str) -> CapabilityResult:
        if name == "local_toolchain":
            return self._check_local_toolchain()
        if name == "gateway":
            return self._check_gateway()
        if name == "flash_helper":
            return self._check_flash_helper()
        if name == "uart_device":
            return self._check_uart_device()
        raise ValueError(f"unknown PQC test capability: {name}")

    def _check_local_toolchain(self) -> CapabilityResult:
        repo_root = _repo_root()
        presets_path = repo_root / "CMakePresets.json"
        if not presets_path.is_file():
            return CapabilityResult(
                "local_toolchain",
                False,
                "CMakePresets.json is missing from the repository root",
            )

        cmake = _run_probe(["cmake", "--version"], cwd=repo_root)
        if not cmake.available:
            return CapabilityResult("local_toolchain", False, f"cmake unavailable: {cmake.reason}")

        ninja = _run_probe(["ninja", "--version"], cwd=repo_root)
        if not ninja.available:
            return CapabilityResult("local_toolchain", False, f"ninja unavailable: {ninja.reason}")

        presets = _run_probe(["cmake", "--list-presets"], cwd=repo_root)
        if not presets.available:
            return CapabilityResult(
                "local_toolchain",
                False,
                f"CMake presets unavailable: {presets.reason}",
            )

        return CapabilityResult("local_toolchain", True, "cmake, ninja, and CMake presets are available")

    def _check_gateway(self) -> CapabilityResult:
        host = _host_config()
        host_alias = _nested(host, "alias")
        if not host_alias:
            return CapabilityResult("gateway", False, f"{DEFAULT_HOST_CONFIG} is missing alias")

        probe = _ssh_probe(host_alias, "true")
        if not probe.available:
            return CapabilityResult("gateway", False, f"SSH gateway probe failed for {host_alias}: {probe.reason}")

        return CapabilityResult("gateway", True, f"SSH gateway probe passed for {host_alias}")

    def _check_flash_helper(self) -> CapabilityResult:
        gateway = self.check("gateway")
        if not gateway.available:
            return CapabilityResult("flash_helper", False, gateway.reason)

        host = _host_config()
        host_alias = _nested(host, "alias")
        helper = _nested(host, "flash", "helper")
        if not host_alias or not helper:
            return CapabilityResult("flash_helper", False, f"{DEFAULT_HOST_CONFIG} is missing flash.helper")

        probe = _ssh_probe(host_alias, f"command -v {helper} >/dev/null 2>&1")
        if not probe.available:
            return CapabilityResult(
                "flash_helper",
                False,
                f"flash helper {helper!r} is unavailable on {host_alias}: {probe.reason}",
            )

        return CapabilityResult("flash_helper", True, f"flash helper {helper!r} is available on {host_alias}")

    def _check_uart_device(self) -> CapabilityResult:
        gateway = self.check("gateway")
        if not gateway.available:
            return CapabilityResult("uart_device", False, gateway.reason)

        host = _host_config()
        host_alias = _nested(host, "alias")
        device = _nested(host, "uart", "device")
        if not host_alias or not device:
            return CapabilityResult("uart_device", False, f"{DEFAULT_HOST_CONFIG} is missing uart.device")

        probe = _ssh_probe(host_alias, f"test -e {device}")
        if not probe.available:
            return CapabilityResult(
                "uart_device",
                False,
                f"UART device {device!r} is unavailable on {host_alias}: {probe.reason}",
            )

        return CapabilityResult("uart_device", True, f"UART device {device!r} is available on {host_alias}")


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("pqc")
    group.addoption(
        "--pqc-require-local-build",
        action="store_true",
        default=False,
        help="Fail instead of skip when the local STM32/CMake/Ninja build capability is unavailable.",
    )
    group.addoption(
        "--pqc-require-gateway",
        action="store_true",
        default=False,
        help="Fail instead of skip when gateway or gateway flash-helper capability is unavailable.",
    )
    group.addoption(
        "--pqc-require-hardware",
        action="store_true",
        default=False,
        help="Fail instead of skip when hardware/UART capability is unavailable.",
    )


def pytest_cmdline_main(config: pytest.Config) -> None:
    mark_expr = str(config.getoption("markexpr") or "").strip()
    if mark_expr in {"short", "long"}:
        setattr(config, DURATION_MARK_EXPR_KEY, mark_expr)
        config.option.markexpr = ""


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: tests that may invoke local toolchains or external capabilities; auto-skip when required capabilities are unavailable",
    )
    config.addinivalue_line(
        "markers",
        "hardware: tests that require physical STM32 hardware, gateway access, or UART capture; auto-skip when required capabilities are unavailable",
    )
    config.addinivalue_line(
        "markers",
        "short: routine confidence tests intended for frequent execution",
    )
    config.addinivalue_line(
        "markers",
        "long: slow, destructive, comprehensive, or full-matrix tests intended for all-in validation",
    )

    mark_expr = str(config.getoption("markexpr") or "").strip()
    if mark_expr in {"short", "long"}:
        setattr(config, DURATION_MARK_EXPR_KEY, mark_expr)
        config.option.markexpr = ""


def _duration_mark_expr(config: pytest.Config) -> str | None:
    return getattr(config, DURATION_MARK_EXPR_KEY, None)


def _has_duration_marker(item: pytest.Item) -> bool:
    return bool(item.get_closest_marker("short") or item.get_closest_marker("long"))


def pytest_itemcollected(item: pytest.Item) -> None:
    """Default unclassified tests to the short suite.

    Hardware benchmark profile parameters and destructive hardware workflows mark
    themselves explicitly as short or long. Existing unit and integration tests
    are routine confidence coverage, so they are short unless a test module or
    parameter says otherwise. Adding the marker during item collection ensures
    `pytest -m short` can select these tests rather than relying on later
    collection-modification ordering.
    """

    if not _has_duration_marker(item):
        item.add_marker(pytest.mark.short)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if not _has_duration_marker(item):
            item.add_marker(pytest.mark.short)

    duration_expr = _duration_mark_expr(config)
    if duration_expr in {"short", "long"}:
        selected: list[pytest.Item] = []
        deselected: list[pytest.Item] = []
        for item in items:
            if item.get_closest_marker(duration_expr):
                selected.append(item)
            else:
                deselected.append(item)
        if deselected:
            config.hook.pytest_deselected(items=deselected)
            items[:] = selected

    items.sort(key=lambda item: (TEST_PHASE_ORDER[_test_phase(item)], item.nodeid))


def pytest_runtest_setup(item: pytest.Item) -> None:
    phase = _test_phase(item)
    failed_lower_phases = [
        lower_phase
        for lower_phase in LOWER_TEST_PHASES[phase]
        if lower_phase in _failed_test_phases(item.config)
    ]
    if not failed_lower_phases:
        return

    failed_phase_list = ", ".join(failed_lower_phases)
    pytest.exit(
        f"Stopping before {phase} tests because lower-level pytest phase(s) failed: {failed_phase_list}",
        returncode=1,
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):
    outcome = yield
    report = outcome.get_result()
    if not report.failed:
        return
    if report.when not in {"setup", "call"}:
        return

    _failed_test_phases(item.config).add(_test_phase(item))


@pytest.fixture(scope="session")
def pqc_capabilities() -> PqcCapabilityChecker:
    return PqcCapabilityChecker()


@pytest.fixture
def pqc_require_capabilities(
    request: pytest.FixtureRequest,
    pqc_capabilities: PqcCapabilityChecker,
):
    def require(*capability_names: str, strict_mode: str) -> None:
        unavailable = [
            pqc_capabilities.check(name)
            for name in capability_names
            if not pqc_capabilities.check(name).available
        ]
        if not unavailable:
            return

        reason = "; ".join(f"{item.name}: {item.reason}" for item in unavailable)
        message = f"PQC capability unavailable: {reason}"

        strict_option_by_mode = {
            "local_build": "--pqc-require-local-build",
            "gateway": "--pqc-require-gateway",
            "hardware": "--pqc-require-hardware",
        }
        option = strict_option_by_mode[strict_mode]
        if request.config.getoption(option):
            pytest.fail(message)
        pytest.skip(message)

    return require