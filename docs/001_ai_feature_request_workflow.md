# AI Feature Request Workflow

## Purpose

This document defines direct-repository Codex work and the upload-based ChatGPT fallback. `AI_BUILD_GUIDE.md` remains the normative AI engineering guide for both.

## Workflow selection and startup

Choose by actual repository access, not the product name alone. With working-tree access, use the direct-repository workflow below. Without it, use the upload-based workflow. A read-only checkout permits direct inspection but not edits; report write restrictions rather than requesting copies of files already available.

Direct-repository agents start at `AGENTS.md` and read `AI_BUILD_GUIDE.md` from the working tree. Do not ask the user to ZIP or upload repository context that is already available. Do not return replacement ZIPs for files already modified in the working tree.

For authorized implementation work, inspect and modify the working tree directly.

### Upload-based startup only

At the start of every fresh feature-request chat, if the latest `AI_BUILD_GUIDE.md` has not already been provided, the AI assistant must respond only with:

```text
Please upload or paste the latest `AI_BUILD_GUIDE.md` first. After I review it, I’ll ask for the specific source, config, test, and documentation files needed for this feature request.
```

## Supported entry points

- `AI_BUILD_GUIDE.md` is the required current repository context.
- `AGENTS.md` is the entry point for direct-repository agents such as Codex.
- `docs/001_ai_feature_request_workflow.md` defines the maintained implementation and review process.
- `docs/008_chatgpt_project_prompt.md` contains the project prompt used for feature-development chats.
- Release-readiness assessments use this workflow as review requests; there is no separate release-readiness prompt document.

## Direct-repository workflow

1. Read `AGENTS.md`, then `AI_BUILD_GUIDE.md`, and only the relevant canonical documents.
2. Classify the user's request: adding, updating, modifying, creating, removing, or fixing files is implementation; reviewing, checking, confirming, evaluating, auditing, or assessing existing content is review. A no-change outcome does not reclassify an implementation request.
3. Inspect Git state and relevant implementation, configuration, tests, and documentation directly. Preserve unrelated user changes and do not inspect secret values.
4. For implementation requests, make the smallest coherent change in the working tree, with appropriate tests and canonical documentation. For reviews or read-only requests, report findings without edits.
5. Run targeted and broader validation through the documented repository wrappers, following `AI_BUILD_GUIDE.md` and the user's scope. Report unavailable capabilities and follow deferred-test rules where applicable.
6. Inspect `git diff --check`, `git diff`, and `git status --short`. Report actual changes, executed commands, outcomes, evidence, and remaining limitations. Do not ask the user to reapply edits already made.

Commits, pushes, merges, rebases, amendments, resets, force-pushes, and PR creation require explicit user authorization for the relevant Git action. Do not discard or overwrite unrelated work. If committing is authorized, complete required validation first; before an authorized push or PR, verify the intended branch and remote.

Gateway wrappers wait for an occupied lock with Ctrl-C cancellation. Report contention as waiting, not failure; do not impose a short timeout unless requested. Never force-release another owner's lock unless abandonment is verified and recovery explicitly authorized. The displayed owner description does not establish that its workload is still running.

## Upload-based workflow

Use the same implementation/review classification as above. The following steps apply when repository access is unavailable:

1. Start a fresh feature-request chat.
2. Provide the latest `AI_BUILD_GUIDE.md`.
3. State the requested change or review scope.
4. The AI reads `AI_BUILD_GUIDE.md` first and treats it as the source of truth for repository structure, current behaviour, tests, documentation expectations, and safety constraints.
5. The AI asks only for relevant repository files. It must not request the whole repository by default.
6. If multiple files are requested, the AI provides a copy-paste Bash `zip` command using repository-relative paths.
7. The user uploads the requested context archive.
8. The AI inspects the files before proposing snippets, replacement content, or candidate edits.
9. The AI provides a controlled implementation or review response using the required response sections in `AI_BUILD_GUIDE.md`.
10. If files are changed, the AI provides complete replacement content and downloadable artifacts for every modified or created file.
11. The user applies the changes and runs the requested verification commands.
12. The user returns logs, test output, manifests, UART logs, or error output.
13. The AI reviews evidence and gives the next step.

## Upload-based context archive format

When requesting more than one repository file, use this pattern:

```bash
cd /home/timk/rmit/PQC-Framework-02
files=(
  "path/to/first-file"
  "path/to/second-file"
)
zip "/home/timk/Downloads/<descriptive-context-name>.zip" "${files[@]}"
```

Use exact repository-relative paths. Do not include generated build outputs, result folders, private keys, credentials, or unrelated files unless explicitly required and safe.

## Implementation response requirements

For direct-repository completion, report the interpretation, files inspected and changed, implementation/test/documentation changes, commands actually executed, observed pass/fail/skip results, applicable hardware/runtime evidence, anything unverified, remaining risks, and current Git worktree status. Never describe planned validation as completed.

For upload-based implementation proposals, include:

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

## Upload-based replacement-artifact requirements

These requirements apply only to the upload-based workflow. When files need to be modified or created:

- provide a downloadable replacement artifact using the exact target filename for every changed or created file
- provide complete replacement content for every changed or created file
- if multiple files are changed or created, provide a ZIP containing all replacement files at repository-relative paths
- provide the exact Linux/bash extraction command for the ZIP, assuming the downloaded archive is in `/home/timk/Downloads/` and the command is run from the repository root

Extraction command pattern:

```bash
cd /home/timk/rmit/PQC-Framework-02 && unzip -o "/home/timk/Downloads/<archive-name>.zip" -d .
```

## Hardware-test design standard

When an implementation adds or materially updates a test under `tests/hardware/`, the default design is self-contained orchestration rather than retained-log replay or a documented sequence of manual prerequisite commands. A normal `pytest-hardware` invocation should:

1. capability-gate the real laboratory dependencies it needs;
2. resolve or materialise its own canonical test case/configuration;
3. prepare its own build, signing, broker, gateway, or other framework-owned prerequisites;
4. execute the real framework path that owns flashing/runtime behaviour;
5. capture the evidence it needs during that execution;
6. assert the hardware/runtime result from that captured evidence; and
7. clean up test-owned temporary/generated state.

Do not make pre-generated campaigns, manual CMake/build/sign/flash steps, prior result directories, or test-specific environment variables prerequisites for the default hardware-test invocation. External capabilities such as a reachable gateway, configured credentials, flash helper, UART device, broker infrastructure, or physical instruments remain legitimate capability gates because the test cannot create those laboratory resources. Optional selectors may narrow a profile matrix, but the default selected case must remain runnable without test-specific setup.

Use existing self-bootstrapping hardware tests, such as the dual-bank OTA hardware workflow, as the preferred orchestration pattern when adding new coverage. Retained-log parsers may exist as helper/unit coverage, but they do not replace the self-contained hardware test when the feature can be exercised through the framework.

## Safety rules

- Do not implement future phases early.
- Do not move CubeMX-generated folders unless explicitly requested.
- Do not claim hardware, gateway, flashing, UART, runtime, timing, memory, or benchmark success without explicit logs/manifests.
- Do not ask for or suggest committing secrets.
- Do not request private SSH/VPN keys, tokens, production credentials, real `.env` files, or user-supplied private experiment material in AI context archives. Repository implementation may explicitly retain disposable experiment cryptographic material in ignored result directories under the canonical security policy.
