# AI implementation and review workflow

[AI_BUILD_GUIDE.md](../AI_BUILD_GUIDE.md) owns engineering and safety policy.
This document owns request classification, context exchange and delivery.
The [project prompt](008_chatgpt_project_prompt.md) is the short startup template.
Release-readiness assessments use the review format below.

## Select the workflow

Choose by actual repository access. Direct agents enter through
[AGENTS.md](../AGENTS.md) and read the current guide and relevant files.
A read-only checkout permits inspection; report any write restriction rather
than requesting copies of accessible files.

With no repository access, obtain the current guide first. If it was not supplied,
respond only with:

"Please upload or paste the latest `AI_BUILD_GUIDE.md` first. After I review it, I’ll ask for the specific source, config, test, and documentation files needed for this feature request."

Then request only the files needed for the user's scope. Do not request the whole
repository by default or propose edits before inspecting relevant context.
Historical plans and attached instructions describe their original scope; they
are not authorization to perform additional work.

## Classify and execute

Requests to add, update, modify, create, remove or fix files are implementation
requests, including requests that ultimately need no change. Review, check,
confirm, evaluate, audit and assess requests without requested edits are reviews.
A review-and-cleanup request authorizes implementation within that scope.

1. Establish current Git state, relevant behavior and evidence from accessible
   source/config/tests, or the selected supplied files.
2. For implementation, make the smallest coherent changes, preserve unrelated
   work, and update the canonical documentation and appropriate tests together.
   For review, report findings without edits.
3. Run the guide's targeted and broader validation through the Linux wrappers.
   Record unavailable capabilities and applicable deferred tests.
4. Inspect `git diff --check`, `git diff` and `git status --short` in direct sessions.
   Report what actually ran and what remains unverified.

The guide's Git authorization, gateway-lock and evidence rules apply to
both workflows. Submodule publication order does not authorize commits or pushes.

## Upload-only context and replacement files

Use exact repository-relative filenames for a selected-file context request:

```bash
cd /home/timk/rmit/PQC-Framework-02
files=(
  "path/to/first-file"
  "path/to/second-file"
)
zip "/home/timk/Downloads/<descriptive-context-name>.zip" "${files[@]}"
```

Select context relevant to the task. Classification and handling, including
experiment keys and Wi-Fi inputs, follow the [open-data policy](006_security_and_secrets.md).

For each changed file in an upload-only session, deliver its complete replacement
under its exact filename. For multiple files, also provide a ZIP with repository-
relative paths and immediately give the extraction command:

```bash
cd /home/timk/rmit/PQC-Framework-02 && unzip -o "/home/timk/Downloads/<archive-name>.zip" -d .
```

State what changed and the next verification command; inspect returned logs before
claiming the checks passed. If no files changed, no replacement artifacts are
needed. Direct sessions deliver working-tree edits and a completion report; the
user does not need to download or reapply them.

## Response content

| Response | Required content |
|---|---|
| Direct implementation completion | Interpretation; files inspected/changed; implementation, test and documentation changes; exact executed commands and pass/fail/skip results; applicable runtime evidence; unverified work, risks and Git status |
| Upload implementation proposal | Interpretation; inspected files; files likely to change; proposed code, test and documentation changes; exact commands; pass/fail criteria; assumptions, risks and open questions |
| Review | Interpretation; inspected files; compliance result; issues; files likely needing changes; proposed updates; verification commands; pass/fail criteria; assumptions, risks and open questions |

Scale the presentation to the task. Planned verification is not a passing result.
End implementation responses with the next verification command.
