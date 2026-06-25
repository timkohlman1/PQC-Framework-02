# AI Feature Request Workflow

## Purpose

This document describes how AI-assisted feature requests should be handled for this repository.

The goal is to reduce the amount of context that must be uploaded for each AI-assisted change while still keeping the AI agent grounded in the current repository structure and implementation state.

## Workflow

1. Start a new feature-request chat.
2. Provide the latest `AI_BUILD_GUIDE.md`.
3. Describe the requested change.
4. Provide only the relevant source, config, test, and documentation files.
5. Ask the AI agent to propose a small controlled change.
6. Apply the change locally.
7. Run the requested verification commands.
8. Return logs for review.
9. Update documentation and `AI_BUILD_GUIDE.md` if behaviour or structure changed.

## Rules for AI Agents

AI agents must not assume repository structure beyond the provided files.

AI agents must not implement future phases early.

AI agents must include tests and documentation updates where appropriate.

AI agents must not claim hardware tests passed unless user-provided logs confirm it.

## Context Files

The first file to provide to an AI agent should be:

```text
AI_BUILD_GUIDE.md
```

Relevant files should then be supplied based on the specific change request.
