# AI Feature Request Workflow

## Purpose

This document defines the AI-assisted development workflow for this repository.

## Startup rule

At the start of every fresh feature-request chat, if the latest `AI_BUILD_GUIDE.md` has not already been provided, the AI assistant must respond only with:

```text
Please upload or paste the latest `AI_BUILD_GUIDE.md` first. After I review it, I’ll ask for the specific source, config, test, and documentation files needed for this feature request.
```

## Supported entry points

- `AI_BUILD_GUIDE.md` is the required current repository context.
- `docs/001_ai_feature_request_workflow.md` defines the maintained implementation and review process.
- `docs/008_chatgpt_project_prompt.md` contains the project prompt used for feature-development chats.
- Release-readiness assessments use this workflow as review requests; there is no separate release-readiness prompt document.

## Workflow

1. Start a fresh feature-request chat.
2. Provide the latest `AI_BUILD_GUIDE.md`.
3. State the requested change or review scope.
4. The AI reads `AI_BUILD_GUIDE.md` first and treats it as the source of truth for repository structure, current behaviour, tests, documentation expectations, and safety constraints.
5. The AI asks only for relevant repository files. It must not request the whole repository by default.
6. If multiple files are requested, the AI provides a copy-paste PowerShell `Compress-Archive` command using repository-relative paths.
7. The user uploads the requested context archive.
8. The AI inspects the files before proposing snippets, replacement content, or candidate edits.
9. The AI provides a controlled implementation or review response using the required response sections in `AI_BUILD_GUIDE.md`.
10. If files are changed, the AI provides complete replacement content and downloadable artifacts for every modified or created file.
11. The user applies the changes and runs the requested verification commands.
12. The user returns logs, test output, manifests, UART logs, or error output.
13. The AI reviews evidence and gives the next step.

## Context archive format

When requesting more than one repository file, use this pattern:

```powershell
$files = @(
  "path/to/first-file",
  "path/to/second-file"
)

Compress-Archive -LiteralPath $files -DestinationPath "C:\Users\timko\Downloads\<descriptive-context-name>.zip" -Force
```

Use exact repository-relative paths. Do not include generated build outputs, result folders, private keys, credentials, or unrelated files unless explicitly required and safe.

## Implementation response requirements

For implementation requests, include:

1. Brief interpretation.
2. Files inspected.
3. Files likely to change.
4. Proposed code changes.
5. Proposed test changes.
6. Proposed documentation updates.
7. Exact commands to run.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

## Review response requirements

For review requests, include:

1. Brief interpretation.
2. Files inspected.
3. Compliance result.
4. Issues found.
5. Files likely needing changes.
6. Proposed updates.
7. Exact verification commands.
8. Expected output or pass/fail criteria.
9. Assumptions, risks, or unresolved questions.

## Replacement-artifact requirements

When files need to be modified or created:

- provide a downloadable replacement artifact using the exact target filename for every changed or created file
- provide complete replacement content for every changed or created file
- if multiple files are changed or created, provide a ZIP containing all replacement files at repository-relative paths
- provide the exact PowerShell extraction command for the ZIP, assuming the downloaded archive is in `C:\Users\timko\Downloads\` and the command is run from the repository root

Extraction command pattern:

```powershell
Expand-Archive -LiteralPath "C:\Users\timko\Downloads\<archive-name>.zip" -DestinationPath . -Force
```

## Safety rules

- Do not implement future phases early.
- Do not move CubeMX-generated folders unless explicitly requested.
- Do not claim hardware, gateway, flashing, UART, runtime, timing, memory, or benchmark success without explicit logs/manifests.
- Do not ask for or suggest committing secrets.
- Do not request private SSH, VPN, TLS, MQTT, firmware-signing, wolfBoot-signing, certificate, `.env`, token, or production credential material.
