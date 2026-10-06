# PQC framework — repository agent entry point

Read [AI_BUILD_GUIDE.md](AI_BUILD_GUIDE.md) before substantive work. It owns the
engineering, testing, evidence and Git rules for this repository.
Use the [documentation index](docs/README.md) to select relevant topic references;
do not read every document for every task.

With repository access, inspect and edit the working tree within the user's
requested scope. Preserve unrelated changes. Do not request uploads of accessible
files or ask the user to reapply edits already made. Without repository access,
use the selected-file upload fallback in the
[AI workflow](docs/001_ai_feature_request_workflow.md).

Linux/bash and `./scripts/dev.sh` are the normal development path. Hardware access
is gateway-mediated. Follow the [open-data policy](docs/006_security_and_secrets.md) for experiment
material. Preserve gateway coordination and require evidence from the affected
boundary before claiming success.

Do not commit, push, create PRs, reset, discard, amend, rebase or merge unless the
user explicitly authorizes the relevant Git action. Before completion, inspect
the diff and Git status, run the applicable validation, and report actual results
and limitations as specified in the guide.
