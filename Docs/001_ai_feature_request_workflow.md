# AI Feature Request Workflow

## Purpose

This document describes how AI-assisted feature requests should be handled for this repository.

The goal is to reduce the amount of context that must be uploaded for each AI-assisted change while still keeping the AI agent grounded in the current repository structure, known-good baseline, implementation state, testing model, and documentation requirements.

## Workflow

1. Start a new feature-request chat.

2. Describe the requested change.

3. Provide the latest `AI_BUILD_GUIDE.md`.

   If the user has not already provided it, the AI agent must ask for the latest `AI_BUILD_GUIDE.md` before proposing code changes.

4. The AI agent reviews `AI_BUILD_GUIDE.md`.

   The guide is the source of truth for:
   - current repository structure
   - known-good baseline
   - development rules
   - testing expectations
   - documentation requirements
   - hardware constraints
   - safety and secret-handling rules
   - current implementation phase

5. The AI agent asks for relevant files only.

   The AI agent must not ask for the full repository by default.

   Relevant files may include:
   - source files likely to change
   - related headers or interfaces
   - config files
   - test files
   - documentation files
   - build files, only if needed

   If more context is required later, the AI agent should ask for the specific missing file and explain why it is needed.

6. The AI agent proposes a small controlled change.

   The proposal should cover:
   - code changes
   - tests to add or update
   - documentation updates
   - verification commands
   - expected pass/fail criteria
   - assumptions, risks, or unresolved questions

7. The user applies the change locally.

8. The user runs the requested verification commands.

9. The user returns logs for review.

   Relevant evidence may include:
   - build logs
   - compiler errors
   - unit test output
   - integration test output
   - flashing logs
   - UART logs
   - runtime output
   - screenshots, if useful

10. The AI agent reviews the logs and updates the next step.

    The next step may be:
    - proceed to the next implementation step
    - fix a build or runtime issue
    - request one additional relevant file
    - update or add tests
    - update documentation
    - revise the implementation plan
    - mark the feature request as complete if verification passes

11. Update documentation and `AI_BUILD_GUIDE.md` if repository behaviour, structure, workflow, commands, testing, or documentation expectations changed.

## Rules for AI Agents

AI agents must not assume repository structure beyond the provided files and the current `AI_BUILD_GUIDE.md`.

AI agents must not implement future phases early.

AI agents must ask for relevant files only and must not request the full repository by default.

AI agents must include tests and documentation updates where appropriate.

AI agents must provide exact verification commands.

AI agents must not claim hardware tests passed unless user-provided logs confirm it.

AI agents must not claim a change is verified unless the user has returned evidence showing that the relevant checks passed.

## Context Files

The first required context file for an AI-assisted feature request is:

```text
AI_BUILD_GUIDE.md