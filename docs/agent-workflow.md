# Agent Workflow

## Project Awareness & Context

- **Always read `docs/development.md`** at the start of a new conversation to understand the project's architecture, goals, style, and constraints.
- **Use consistent naming conventions, file structure, and architecture patterns** as described in `docs/development.md`.
- The `docs/tasks.md` file is used to track the implementation of new features.

## Task Completion

- Check `docs/tasks.md`** before starting a new task. If the task isn’t listed, add it with a brief description and today's date under 'New Tasks'.
- **Mark completed tasks in `docs/tasks.md`** with '[x]' markers upon completion immediately after finishing them.

## Documentation & Explainability

- **Update `README.md`** when new features are added, dependencies change, or setup steps are modified.
- **Comment non-obvious code** and ensure everything is understandable to a mid-level developer.
- When writing complex logic, **add an inline `# Reason:` comment** explaining the why, not just the what.
- if a new memorable relation was discovered during a task, **Update `/docs/tasks.md`** with this information under `### MEMORY` with date of discovery.

## AI Behavior Rules

- **Never assume missing context. Ask questions if uncertain.**
- **Never hallucinate libraries or functions** – only use known, verified packages.
- **Always confirm file paths and module names** exist before referencing them in code or tests.
- **Never delete or overwrite existing code** unless explicitly instructed to or if part of a task from `docs/tasks.md`.

## Code Structure & Modularity

- **Never create a file longer than 800 lines of code, except for single file applications.**
    - If a file approaches this limit, refactor by splitting it into modules or helper files.
- **Organize code into clearly separated modules**, grouped by feature or responsibility.
- **Use clear, consistent imports**, prefer relative imports within packages.
