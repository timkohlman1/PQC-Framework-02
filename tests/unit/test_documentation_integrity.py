"""Documentation structure/navigation contracts, deliberately independent of prose."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import json
import argparse
import importlib.util
import shlex
import sys
from unittest.mock import patch
import subprocess
from urllib.parse import unquote, urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
INDEX = "docs/README.md"
ARCHITECTURE = "docs/007_framework_architecture.md"
CONFIGURATION = "docs/011_experiment_configuration.md"
RESULTS = "docs/012_results_and_analysis.md"
TESTING = "docs/013_testing_and_deferred_coverage.md"
AI_DOCUMENTS = (
    "AGENTS.md", "AI_BUILD_GUIDE.md", "docs/001_ai_feature_request_workflow.md",
    "docs/008_chatgpt_project_prompt.md",
)
LINK = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
INDEX_ROW = re.compile(r"^\| \[([^]]+)\]\([^)]+\) \|")


def read(path: str) -> str:
    content = (ROOT / path).read_text(encoding="utf-8-sig")
    if Path(path).suffix == ".ipynb":
        return "\n".join("".join(cell["source"]) for cell in json.loads(content)["cells"]
                         if cell["cell_type"] == "markdown")
    return content


@lru_cache(maxsize=1)
def repository_files() -> set[str]:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT}", "ls-files", "--cached",
         "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, capture_output=True,
    )
    return {p.decode() for p in result.stdout.split(b"\0") if p}


@lru_cache(maxsize=1)
def submodule_roots() -> tuple[str, ...]:
    return tuple(path.rstrip("/") + "/" for path in re.findall(
        r"(?m)^\s*path\s*=\s*(\S+)\s*$", read(".gitmodules")))


def project_owned(path: str) -> bool:
    if any(path.startswith(root) for root in submodule_roots()):
        return False
    if path.startswith(("Drivers/", "Middlewares/", "LWIP/", "build/", "results/",
                        ".pqc-generated-state/")):
        return False
    candidate = Path(path)
    if ".ipynb_checkpoints" in candidate.parts:
        return False
    return candidate.suffix in {".md", ".rst", ".adoc", ".ipynb"} or (
        path.startswith("docs/") and candidate.suffix == ".txt"
    )


def index_rows(content: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in content.splitlines():
        match = INDEX_ROW.match(line)
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert len(cells) == 3 and all(cells), f"Incomplete index row: {line}"
        rows.append((match[1], cells[1], cells[2]))
    return rows


def outside_fences(content: str) -> str:
    lines = []
    fence = None
    for line in content.splitlines():
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if match:
            token, tail = match.groups()
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not tail.strip():
                fence = None
            continue
        if fence is None:
            lines.append(line)
    assert fence is None, "Unclosed fenced code block"
    return "\n".join(lines)


def anchors(content: str) -> set[str]:
    prose = outside_fences(content)
    found = set(re.findall(r'<(?:a|h[1-6])\s+[^>]*(?:id|name)="([^"]+)"', prose))
    counts: dict[str, int] = {}
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", prose):
        heading = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", heading)
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        duplicate = counts.get(slug, 0)
        counts[slug] = duplicate + 1
        found.add(f"{slug}-{duplicate}" if duplicate else slug)
    return found


def local_link_errors(source: Path, content: str, root: Path) -> list[str]:
    errors = []
    for destination in LINK.findall(outside_fences(content)):
        url = urlsplit(destination.strip("<>"))
        if url.scheme or url.netloc:
            continue
        target = (source.parent / unquote(url.path)).resolve() if url.path else source
        if not target.is_relative_to(root):
            errors.append(f"link leaves repository: {destination}")
        elif not target.exists():
            errors.append(f"missing link: {destination}")
        elif url.fragment and target.suffix == ".md":
            if unquote(url.fragment) not in anchors(target.read_text(encoding="utf-8-sig")):
                errors.append(f"missing anchor: {destination}")
    return errors


def active_documents() -> list[str]:
    return [path for path, _role, status in index_rows(read(INDEX))
            if status not in {"Historical plan", "Decision record"}]


def test_index_covers_all_project_documents_including_unstaged_additions():
    rows = index_rows(read(INDEX))
    indexed = [row[0] for row in rows]
    expected = sorted(path for path in repository_files() if project_owned(path))
    assert len(indexed) == len(set(indexed)), "Duplicate index paths"
    assert indexed == sorted(indexed), "Keep inventory paths sorted"
    assert set(indexed) == set(expected), (
        f"Missing: {sorted(set(expected) - set(indexed))}; "
        f"unexpected: {sorted(set(indexed) - set(expected))}"
    )
    for path, _role, status in rows:
        assert (ROOT / path).is_file(), path
        assert status in {"Current reference", "Operational guide", "AI workflow",
                          "Historical plan", "Decision record", "Executable notebook",
                          "Exploratory notebook"}, (path, status)


def test_current_document_links_and_anchors_resolve():
    failures = []
    for path, _role, _status in index_rows(read(INDEX)):
        failures.extend(f"{path}: {error}" for error in local_link_errors(ROOT / path, read(path), ROOT))
    assert not failures, "\n".join(failures)


def test_entry_points_route_to_one_index_and_normative_guide():
    for path in ("README.md", "AGENTS.md", "AI_BUILD_GUIDE.md"):
        assert INDEX in read(path), path
    for path in AI_DOCUMENTS:
        if path != "AI_BUILD_GUIDE.md":
            assert "AI_BUILD_GUIDE.md" in read(path), path
    for owner in (ARCHITECTURE, CONFIGURATION, RESULTS, TESTING):
        assert owner in read("AI_BUILD_GUIDE.md"), owner
    for owner in (CONFIGURATION, RESULTS, TESTING):
        assert Path(owner).name in read(ARCHITECTURE), owner


def test_documented_python_and_pytest_command_targets_exist():
    for path in active_documents():
        content = read(path).replace("\\\n", " ")
        for line in content.splitlines():
            # Deferred rows name future contracts explicitly; they are not runnable examples.
            if path == TESTING and line.startswith("| DTR-"):
                continue
            if not re.search(r"(?:\./scripts/dev\.sh (?:python|pytest)|python3? )", line):
                continue
            for target in re.findall(r"(?<![\w/])((?:scripts|tests|experiment)/[\w./-]+\.py)", line):
                assert (ROOT / target).is_file(), f"{path}: missing command target {target}"


def test_deferred_register_is_unique_and_all_rows_are_complete():
    owners = [path for path in active_documents() if re.search(r"(?m)^\| DTR-", read(path))]
    assert owners == [TESTING], owners
    rows = [line for line in read(TESTING).splitlines() if line.startswith("| DTR-")]
    assert rows
    identifiers = set()
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) == 8 and all(cells), row
        assert re.fullmatch(r"DTR-[A-Z0-9-]+", cells[0]), row
        assert cells[0] not in identifiers, cells[0]
        identifiers.add(cells[0])
        assert "tests/" in cells[5] and "scripts/" in cells[6], row
        for target in re.findall(r"tests/[\w./-]+\.py", cells[5]):
            assert (ROOT / target).is_file() or "planned" in cells[5].lower(), (
                f"{cells[0]} names absent test without marking it planned: {target}"
            )


def test_documented_workload_catalog_matches_resolver_profiles():
    catalog = {}
    for path in (ROOT / "configs/workloads").glob("*.yaml"):
        profile = yaml.safe_load(path.read_text())
        catalog[profile["id"]] = profile["firmware_application"]
    documented = dict(re.findall(r"(?m)^\| `([\w-]+)` \| `([\w-]+)` \|", read(CONFIGURATION)))
    assert documented == catalog


def test_current_docs_do_not_publish_destructive_signing_cleanup_commands():
    for path in active_documents():
        # Inspect shell examples only; prohibitions may legitimately name these commands in prose.
        examples = re.findall(r"```(?:bash|sh|shell)\n(.*?)\n```", read(path), re.S)
        for example in examples:
            assert not re.search(r"(?m)^\s*(?:make\b[^\n]*\bkeysclean\b|rm\b[^\n]*(?:secrets/wolfboot|keystore\.c|signing_private_key))", example), path


@pytest.mark.parametrize("path, expected", [
    ("analysis_implementation_requests.md", True),
    ("experiment/mqtt-broker/config/oqs-mtls/README.md", True),
    ("docs/new-reference.md", True),
    ("scripts/README.md", True),
    ("notebooks/new-analysis.ipynb", True),
    ("notebooks/.ipynb_checkpoints/new-checkpoint.ipynb", False),
    ("docs/new-reference.rst", True),
    ("Drivers/vendor/README.md", False),
    ("tools/wolfboot/README.md", False),
    ("Middlewares/Third_Party/wolfSSL/README.md", False),
    ("instruments/esp32_ina228/lib/SparkFun_Toolkit/README.md", False),
    ("results/run/README.md", False),
])
def test_inventory_boundary(path, expected):
    assert project_owned(path) is expected


def test_link_checker_detects_missing_file_and_anchor_but_ignores_examples(tmp_path):
    source = tmp_path / "index.md"
    target = tmp_path / "topic.md"
    target.write_text("# Heading\n## Repeated `item`\n## Repeated `item`\n")
    content = """[valid](topic.md#heading)
[duplicate](topic.md#repeated-item-1)
[missing](absent.md)
[stale anchor](topic.md#old)
[web](https://example.invalid/topic)
```markdown
[example](not-a-real-file.md)
```
"""
    errors = local_link_errors(source, content, tmp_path)
    assert errors == ["missing link: absent.md", "missing anchor: topic.md#old"]


def test_index_parser_rejects_missing_metadata():
    with pytest.raises(AssertionError, match="Incomplete index"):
        index_rows("| [docs/new.md](new.md) | | Current reference |")


def test_unclosed_fence_is_reported():
    with pytest.raises(AssertionError, match="Unclosed"):
        outside_fences("# Title\n```bash\necho example\n")


PARSER_SOURCES = {
    "scripts/experiment.py": "build_arg_parser",
    "scripts/run_campaign.py": "build_parser",
    "experiment/mqtt-broker/scripts/mqtt_broker_ctl.py": "build_parser",
    "scripts/run_queue.py": None,
    "scripts/collect_thesis_evidence.py": None,
    "scripts/provision_certificates.py": "build_parser",
    "scripts/ready_metrics_2_reliability_v2.py": None,
}


@lru_cache(maxsize=None)
def command_parser(source):
    """Construct real parsers only; never dispatch a documented operation."""
    name = "documentation_cli_" + Path(source).stem
    spec = importlib.util.spec_from_file_location(name, ROOT / source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    builder = PARSER_SOURCES[source]
    if builder:
        return getattr(module, builder)()

    class ParserReady(Exception):
        pass

    captured = []

    def capture(parser, *args, **kwargs):
        captured.append(parser)
        raise ParserReady

    # These host launchers construct their parser at main's start. Interrupt at
    # parse_args, before queue files, provisioning or Docker can be touched.
    with patch.object(argparse.ArgumentParser, "parse_args", capture):
        with pytest.raises(ParserReady):
            module.main([])
    assert len(captured) == 1
    return captured[0]


def documented_cli_commands(content):
    for block in re.findall(r"```(?:bash|sh|shell)\n(.*?)\n```", content, re.S):
        for line in block.replace("\\\n", " ").splitlines():
            words = shlex.split(line, comments=True)
            if not words:
                continue
            if words[0] == "./scripts/dev.sh" and len(words) > 1:
                wrapper = words[1]
                if wrapper in {"experiment", "experiment-gateway"}:
                    yield "scripts/experiment.py", words[2:]
                elif wrapper in {"campaign", "campaign-gateway"}:
                    yield "scripts/run_campaign.py", words[2:]
                elif wrapper in {"python", "python-gateway"} and len(words) > 2:
                    if words[2] in PARSER_SOURCES:
                        yield words[2], words[3:]
            elif words[0] in {"python", "python3"} and len(words) > 1:
                if words[1] in PARSER_SOURCES:
                    yield words[1], words[2:]


def test_documented_cli_arguments_match_real_parsers_without_dispatch():
    checked = set()
    for path in active_documents():
        for source, arguments in documented_cli_commands(read(path)):
            parser = command_parser(source)
            if "--help" in arguments:
                continue
            try:
                parsed = parser.parse_args(arguments)
            except SystemExit as exc:
                pytest.fail(f"{path}: invalid {source} arguments {arguments}: {exc}")
            # This compatibility command still calls removed provision-certs by
            # default; examples must select the functioning preprovisioned path.
            if getattr(parsed, "command", None) == "mqtt-broker-experiment":
                assert parsed.no_provision_certs, path
            checked.add(source)
    assert checked == set(PARSER_SOURCES)


def test_command_extraction_and_parser_reject_removed_broker_option():
    content = "```bash\n./scripts/dev.sh python-gateway experiment/mqtt-broker/scripts/mqtt_broker_ctl.py \\\n  status --profile oqs\n```"
    commands = list(documented_cli_commands(content))
    assert commands == [("experiment/mqtt-broker/scripts/mqtt_broker_ctl.py", ["status", "--profile", "oqs"])]
    with pytest.raises(SystemExit):
        command_parser(commands[0][0]).parse_args(["status", "--host-config", "old.yaml"])


def test_ai_entry_points_and_history_route_to_current_data_policy():
    policy = "006_security_and_secrets.md"
    for path in AI_DOCUMENTS:
        assert policy in {Path(urlsplit(link).path).name for link in LINK.findall(read(path))}, path
    for path, _role, status in index_rows(read(INDEX)):
        if status in {"Historical plan", "Decision record"}:
            links = LINK.findall(read(path).split("\n## ", 1)[0])
            assert any(Path(urlsplit(link).path).name == policy for link in links), path
            assert any(Path(urlsplit(link).path).name in {
                "007_framework_architecture.md", "009_dual_bank_ota_workflow.md",
                "012_results_and_analysis.md",
            } for link in links), path


def test_host_docker_launchers_are_not_documented_inside_development_container():
    launchers = {"scripts/provision_certificates.py", "scripts/run_queue.py",
                 "scripts/collect_thesis_evidence.py", "scripts/ready_metrics_2_reliability_v2.py"}
    for path in active_documents():
        for block in re.findall(r"```(?:bash|sh|shell)\n(.*?)\n```", read(path), re.S):
            for source in launchers:
                assert not re.search(r"\./scripts/dev\.sh (?:python|run python3?) " + re.escape(source), block), (path, source)
