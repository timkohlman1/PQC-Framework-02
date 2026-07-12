from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_AI_DOCUMENTS = (
    "AI_BUILD_GUIDE.md",
    "README.md",
    "docs/001_ai_feature_request_workflow.md",
    "docs/008_chatgpt_project_prompt.md",
)
OBSOLETE_REFERENCES = (
    "docs/009_chatgpt_project_prompt_release_readiness_review.md",
    "docs/phase11_plan.md",
    "docs/plase11_checklist.md",
)
PROJECT_DOCUMENT_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(AI_BUILD_GUIDE\.md|README\.md|docs/[A-Za-z0-9_./-]+\.(?:md|txt))"
)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _tracked_files() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return {
        path.decode("utf-8")
        for path in completed.stdout.split(b"\0")
        if path
    }


def test_explicit_ai_documentation_references_exist_and_are_tracked() -> None:
    tracked = _tracked_files()

    for source in ACTIVE_AI_DOCUMENTS:
        assert source in tracked, f"Active AI document is not tracked: {source}"
        content = _read(source)
        references = set(PROJECT_DOCUMENT_REFERENCE.findall(content))

        for reference in sorted(references):
            assert (REPO_ROOT / reference).is_file(), (
                f"{source} references missing project documentation: {reference}"
            )
            assert reference in tracked, (
                f"{source} references untracked project documentation: {reference}"
            )


def test_obsolete_ai_workflow_references_are_absent() -> None:
    for source in ACTIVE_AI_DOCUMENTS:
        content = _read(source)
        for obsolete_reference in OBSOLETE_REFERENCES:
            assert obsolete_reference not in content, (
                f"{source} still references obsolete documentation: "
                f"{obsolete_reference}"
            )


def test_supported_ai_entry_points_are_consistent() -> None:
    documents = {
        "AI_BUILD_GUIDE.md": _read("AI_BUILD_GUIDE.md"),
        "README.md": _read("README.md"),
        "docs/001_ai_feature_request_workflow.md": _read(
            "docs/001_ai_feature_request_workflow.md"
        ),
        "docs/008_chatgpt_project_prompt.md": _read(
            "docs/008_chatgpt_project_prompt.md"
        ),
    }

    for content in documents.values():
        assert "AI_BUILD_GUIDE.md" in content
        assert "docs/001_ai_feature_request_workflow.md" in content
        assert "there is no separate release-readiness prompt document" in content.lower()

    for path, content in documents.items():
        if path != "docs/008_chatgpt_project_prompt.md":
            assert "docs/008_chatgpt_project_prompt.md" in content
