---
name: smith.init
description: Initialize SpecKit on a new or existing project — scans the codebase, interviews you about project details, and generates CLAUDE.md, constitution.md, and the full .specify/ scaffolding with commands and agents.
argument-hint: [--preset flask-react|fastapi-next|cli-python|express-react]
---

# SpecKit Project Initialization

Bootstrap a project with the full SpecKit spec-driven development workflow. This skill scans the existing codebase to pre-fill answers, interviews you about your project, and generates all configuration files.

**Arguments:** $ARGUMENTS

## Workflow

### Phase 0: Locate Skill Assets

The SpecKit skill assets (templates, scripts, commands, agents) are bundled at:

```
~/.claude/skills/smith/
├── templates/          # spec, plan, tasks, checklist, agent-file templates
├── scripts/            # Shell scripts for feature management
├── commands/           # Slash command definitions (smith.specify, etc.)
└── agents/             # Agent definitions (architect, senior-qa, etc.)
```

Verify this directory exists. If missing, abort with: "SpecKit skill assets not found at ~/.claude/skills/smith/. Please reinstall the skill."

### Phase 1: Preset Check

If `$ARGUMENTS` contains `--preset <name>`, load preset defaults and skip to Phase 3 (confirmation). Available presets:

| Preset | Stack |
|--------|-------|
| `flask-react` | Flask 3.x + React 19 + SQLite + Tailwind + Poetry + npm |
| `fastapi-next` | FastAPI + Next.js + PostgreSQL + TypeScript + pip + npm |
| `cli-python` | Python CLI (Click/Typer) + no frontend + Poetry |
| `express-react` | Express.js + React 19 + PostgreSQL + TypeScript + npm |

If no preset, proceed to Phase 2.

### Phase 2: Codebase Detection

Scan the current working directory to detect existing project characteristics. For each signal found, record it as a pre-filled answer. Present findings as a detection report before asking questions.

#### 2.1 Project Identity Detection

- Check for existing `CLAUDE.md` — extract project name and description if present
- Check for `package.json` → extract `name`, `description`
- Check for `pyproject.toml` → extract `[tool.poetry].name`, `description`
- Check for `Cargo.toml` → extract `[package].name`, `description`
- Check for `go.mod` → extract module name
- Check for `README.md` → extract first heading and description paragraph
- Check git remote URL for project name hints

#### 2.2 Tech Stack Detection

**Frontend:**
- `package.json` dependencies: `react` → React, `vue` → Vue, `svelte` → Svelte, `next` → Next.js, `@angular/core` → Angular
- `package.json` dependencies: `tailwindcss` → Tailwind, `styled-components`, `@emotion/react`, `sass`
- `tsconfig.json` exists → TypeScript; otherwise JavaScript
- Check for Storybook: `.storybook/` dir or `@storybook/*` in devDeps

**Backend:**
- `pyproject.toml` or `requirements.txt`: `flask` → Flask, `fastapi` → FastAPI, `django` → Django
- `package.json` dependencies: `express` → Express, `fastify` → Fastify, `hono` → Hono
- `go.mod` → Go
- `Cargo.toml` → Rust
- `Gemfile`: `rails` → Rails, `sinatra` → Sinatra

**Database:**
- `pyproject.toml`/`requirements.txt`: `sqlalchemy` → SQLAlchemy, `psycopg2`/`asyncpg` → PostgreSQL, `pymongo` → MongoDB
- `package.json`: `prisma` → Prisma, `typeorm` → TypeORM, `mongoose` → MongoDB, `pg` → PostgreSQL, `better-sqlite3`/`sqlite3` → SQLite
- Look for `*.db` or `*.sqlite` files → SQLite
- Look for `docker-compose.yml` services: `postgres`, `mysql`, `redis`, `mongo`

**Package Managers:**
- `poetry.lock` → Poetry; `Pipfile.lock` → Pipenv; `requirements.txt` → pip
- `package-lock.json` → npm; `yarn.lock` → Yarn; `pnpm-lock.yaml` → pnpm
- `Cargo.lock` → Cargo; `go.sum` → Go modules

**Auth:**
- Search for `oauth`, `jwt`, `passport`, `flask-login`, `next-auth`, `auth0` in dependencies or code

#### 2.3 Tooling Detection

- **Linting**: `.eslintrc*` or `eslint.config.*` → ESLint; `ruff.toml` or `[tool.ruff]` in pyproject.toml → Ruff; `.pylintrc` → Pylint
- **Formatting**: `.prettierrc*` → Prettier; Ruff format → Ruff
- **Testing**: `vitest` or `jest` in package.json → Vitest/Jest; `pytest` in pyproject.toml → Pytest; `go test` patterns → Go test
- **CI/CD**: `.github/workflows/` → GitHub Actions; `.gitlab-ci.yml` → GitLab CI; `Jenkinsfile` → Jenkins
- **Docker**: `Dockerfile` or `docker-compose.yml` → Docker
- **Storybook**: `.storybook/` directory → Storybook

#### 2.4 Structure Detection

- `frontend/` + `backend/` → Web app (separate dirs)
- `src/` only → Single project
- `apps/` or `packages/` → Monorepo
- `ios/` or `android/` → Mobile
- Check for existing `.specify/`, `.claude/commands/`, `.claude/agents/`

#### 2.5 Existing Configuration Detection

- Check for existing `CLAUDE.md` — warn user it will be regenerated (offer to preserve or replace)
- Check for existing `.specify/` — warn and offer to update or replace
- Check for existing `.claude/commands/` — same
- Check for existing `.claude/agents/` — same
- Check for existing constitution at `.specify/memory/constitution.md`

#### 2.6 Present Detection Report

Display findings in a clear table:

```markdown
## Codebase Detection Report

| Category | Detected | Confidence | Value |
|----------|----------|------------|-------|
| Project Name | Yes | High | "my-project" (from package.json) |
| Frontend | Yes | High | React 19 + TypeScript |
| Styling | Yes | High | Tailwind CSS |
| Backend | Yes | High | Flask 3.x + Python 3.12 |
| Database | Yes | Medium | SQLite (found .db files) |
| Auth | No | — | Not detected |
| Linting | Yes | High | ESLint + Ruff |
| Testing | Yes | High | Vitest + Pytest |
| CI/CD | Yes | High | GitHub Actions |
| Docker | Yes | High | Docker Compose |
| Storybook | No | — | Not detected |

Items marked "No" or "Medium" confidence will be asked about in the interview.
```

### Phase 3: Generate Init Intake Document

Instead of prompting the user interactively, generate a persistent intake document at `specs/init-intake.md`.

**IMPORTANT**: This file is the permanent record of project configuration decisions. **Never delete it.** If it already exists, read it and use the existing answers — do not regenerate unless the user explicitly asks to refresh it.

#### 3.1 Create `specs/` directory if it doesn't exist

```bash
mkdir -p specs
```

#### 3.2 If `specs/init-intake.md` does NOT exist, generate it

Create `specs/init-intake.md` with:
- A frontmatter block with generation date, project name, and status
- The full **Codebase Detection Report** table from Phase 2
- All 28 questions organized in 5 groups (Project Identity, Tech Stack, Development Tooling, Quality Standards, Workflow Preferences)
- For each question: the options, a **Recommended** answer with rationale based on codebase detection, and an **Answer** field pre-filled with the recommendation
- A **Project-Specific Notes** section capturing any important context detected during the scan that doesn't fit the standard questions (e.g., multi-service architecture, N8N workflows, custom patterns)

The recommended answers should be based on:
1. High-confidence codebase detections (use detected values directly)
2. Best practices for the detected stack (when no detection available)
3. Project context from memory, STATUS.md, or other project docs

#### 3.3 If `specs/init-intake.md` ALREADY exists, read and use it

Parse the existing file to extract the **Answer** lines for each question. These answers drive all subsequent file generation in Phase 4. Tell the user: "Found existing `specs/init-intake.md` — using your recorded answers. Edit the file and re-run `/smith` to change any decisions."

#### 3.4 Interactive Walkthrough

After generating (or loading) the intake document, walk the user through **every question interactively**, one at a time. For each question, present:

1. **Question number and text** (e.g., "Q5. Frontend framework")
2. **Context** — why this decision matters for the project
3. **Options** — each option with a brief explanation of trade-offs
4. **Recommended answer** — your recommendation with reasoning based on codebase detection and project context
5. **Current answer** — what is currently recorded in the intake file

Then wait for the user's response. Accepted responses:
- A specific choice → update the Answer line in `specs/init-intake.md` immediately
- "ok" / "yes" / pressing enter with no input / confirming the recommendation → keep the current answer, move to next question
- A question or comment → answer it, then re-present the same question
- "skip" → keep current answer, move to next question
- "back" → return to the previous question

After all questions are answered, present a final summary table of all answers and ask the user to confirm before proceeding to Phase 4.

Update `specs/init-intake.md` in real-time as the user answers — do not batch updates.

### Phase 4: Generate Files

After the interactive walkthrough is complete and the user confirms, generate all project files.

#### 4.1 Scaffold Project Directories

Create the directory structure and copy files from the skill assets:

```bash
mkdir -p .specify/memory .specify/templates .specify/scripts/bash
mkdir -p docs/sessions
mkdir -p specs/questions
mkdir -p .smith/vault/sessions .smith/vault/agents .smith/vault/queue .smith/vault/bank .smith/vault/ledger
```

The `docs/sessions/` directory holds session chat logs (timestamped Q&A records with YAML frontmatter for searchability). The `specs/questions/` directory holds structured question files generated before complex changes (numbered questions with options, recommendations, and answer fields). Both are required by the global workflow tenets in `~/.claude/CLAUDE.md`.

The `.smith/vault/ledger/` directory holds the Ledger — Smith's learned knowledge from past workflow executions. After creating the directory, scaffold the Ledger template files: `patterns.md`, `antipatterns.md`, `tool-preferences.md`, `edge-cases.md`, `project-quirks.md` (each with a header and empty-state message), and `meta.yaml` (initialized with creation date and zero counters). See the `smith-reflect` skill for the exact file formats.

Copy from `~/.claude/skills/smith/`:
- `templates/*` → `.specify/templates/`
- `scripts/*` → `.specify/scripts/bash/`

Make scripts executable:
```bash
chmod +x .specify/scripts/bash/*.sh
```

#### 4.2 Generate Constitution (`.specify/memory/constitution.md`)

Generate a constitution file using the interview answers. Structure:

```markdown
# [Project Name] Constitution

## Core Principles

### I. Code Quality Standards
[Generated based on detected linters, languages, component patterns]

### II. Testing Standards
[Generated based on detected test frameworks, coverage target from Q20]

### III. User Experience Consistency
[Generated only if frontend detected — based on styling framework, component tool]

### IV. Performance Requirements
[Generated from Q21 answers, or standard defaults]

## Technology Constraints
[Generated from tech stack answers Q5-Q13]

## Development Workflow

### Branch Strategy
[Generated from Q25]

### SpecKit Workflow
[Standard — always included]

### Commit Standards
[Generated from Q26, Q28]

### Quality Gates
[Generated from Q23, Q27]

## Governance
[Standard boilerplate with project name, version 1.0.0, current date]
```

Use the following rules for content generation:
- **Python backend**: Include Ruff linting, Pydantic validation, snake_case naming
- **JavaScript/TypeScript frontend**: Include ESLint, PascalCase components, camelCase functions
- **React + Storybook**: Include component directory pattern, Storybook-first development
- **Tailwind**: Include "Tailwind utility classes required; custom CSS MUST be justified"
- **Docker**: Include container-related standards
- **SQLAlchemy**: Include "No N+1 queries" rule
- Only include sections relevant to the detected/selected stack

#### 4.3 Generate CLAUDE.md

Generate a CLAUDE.md file at the project root using the interview answers. Structure:

```markdown
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
[Project name and description from Q1-Q2]

### Project Governance
See `.specify/memory/constitution.md` for binding project principles.

### Business Domain
[Domain from Q3, entities from Q4 if provided]

## Tech Stack

### Frontend
[From Q5-Q7, only if frontend exists]

### Backend
[From Q8-Q12, only if backend exists]

## Git Commit Guidelines
[Generated from Q26, Q28 — include linking format, co-author trailer]

## Common Commands

### CI/CD Scripts
[Generated based on detected CI scripts, or suggest creating them]

### Docker Development
[Generated only if Docker detected]

### Frontend Development
[Generated from frontend stack — npm/yarn commands]

### Backend Development
[Generated from backend stack — poetry/pip commands, test commands]

### Database
[Generated from database choice — migration commands if ORM detected]

## Architecture

### Backend Structure
[Generated from directory scan or standard template for the stack]

### Frontend Structure
[Generated from directory scan or standard template for the stack]

### Key Patterns
[Generated based on stack — e.g., "Application Factory" for Flask, "API Routes" for Next.js]

## SpecKit Workflow
[Standard section — always included, customized with review gate selections from Q27]

### Issue-Driven Workflow
[Standard — customized with issue tracker from Q24]

### Subagent Usage
[Standard — always included]

### Review Gates (Mandatory)
[Generated from Q27 selections]

### When Asked "What's Next?"
[Standard — always included]

### Directory Structure
[Standard .specify/ structure]

### Branch Naming
[From Q25]

## E2E Testing with Playwright MCP
[Generated only if Playwright MCP selected in Q19]
```

**IMPORTANT rules for CLAUDE.md generation:**
- Only include sections relevant to the stack (no Docker section if no Docker, no Storybook section if no Storybook, etc.)
- Generate actual commands based on the real package manager and frameworks
- If existing CLAUDE.md was found and user chose to preserve, merge new sections with existing content
- Include the SpecKit Workflow section verbatim — this is the standard workflow

#### 4.4 Set Up `.claude/commands/`

Create the project's `.claude/commands/` directory and copy command files from the skill assets:

```bash
mkdir -p .claude/commands
```

Copy from `~/.claude/skills/smith/commands/`:
- All `smith.*.md` files → `.claude/commands/`
- `review-respond.md` → `.claude/commands/`

#### 4.5 Set Up `.claude/agents/` (Optional)

If the user selected review gates in Q27, create custom agent definitions:

```bash
mkdir -p .claude/agents
```

Copy from `~/.claude/skills/smith/agents/`:
- If architect gate enabled: `architect.md` → `.claude/agents/`
- If product-manager gate enabled: `product-manager.md` → `.claude/agents/`
- Always copy: `senior-qa.md`, `staff-backend.md`, `staff-frontend.md`, `staff-fullstack.md`, `staff-infrastructure.md`

After copying, replace `[PROJECT_NAME]` placeholders in the agent files with the actual project name from Q1.

#### 4.6 Create `.claude/settings.json` (if not exists)

If no `.claude/settings.json` exists, create one with sensible defaults:

```json
{
  "permissions": {
    "allow": [
      "Bash(git status:*)",
      "Bash(git log:*)",
      "Bash(git diff:*)",
      "Bash(git branch:*)",
      "Bash(./.specify/scripts/*:*)"
    ]
  }
}
```

Add framework-specific permissions based on detected stack:
- npm projects: `"Bash(npm run:*)"`, `"Bash(npm install:*)""`
- Poetry projects: `"Bash(poetry run:*)"`, `"Bash(poetry install:*)"`
- Docker projects: `"Bash(docker:*)"`, `"Bash(docker compose:*)"`
- CI scripts: `"Bash(./scripts/*:*)"`

If `.claude/settings.json` already exists, do NOT overwrite — inform the user they may want to add the `.specify/scripts` permission manually.

#### 4.7 Create `.gitignore` Entries

If `.gitignore` exists, append SpecKit-related entries if not already present:

```
# SpecKit / Claude Code
.claude/agent-memory/
.claude/todos/
```

If `.gitignore` doesn't exist, create one with standard patterns for the detected stack plus the above entries.

### Phase 5: Verification & Report

After generating all files, present a summary:

```markdown
## SpecKit Initialization Complete

### Files Created
| File | Status |
|------|--------|
| `CLAUDE.md` | Created / Updated |
| `.specify/memory/constitution.md` | Created |
| `.specify/templates/` (5 files) | Created |
| `.specify/scripts/bash/` (5 files) | Created |
| `.claude/commands/` (10 files) | Created |
| `.claude/agents/` (7 files) | Created |
| `.claude/settings.json` | Created / Skipped (exists) |
| `docs/sessions/` | Created (session chat logs) |
| `specs/questions/` | Created (pre-implementation question files) |
| `specs/init-intake.md` | Created (permanent project config decisions) |

### Available Commands
| Command | Description |
|---------|-------------|
| `/smith.specify <description>` | Create feature spec |
| `/smith.clarify` | Clarify spec ambiguities |
| `/smith.plan` | Generate implementation plan |
| `/smith.tasks` | Generate task breakdown |
| `/smith.analyze` | Cross-artifact consistency check |
| `/smith.implement` | Execute tasks |
| `/smith.checklist` | Generate quality checklist |
| `/smith.constitution` | Update project constitution |

### Next Steps
1. Review `CLAUDE.md` and `.specify/memory/constitution.md` — adjust any generated content
2. Commit the generated files: `git add CLAUDE.md .specify/ .claude/ && git commit -m "chore: initialize SpecKit workflow"`
3. Start your first feature: `/smith.specify <your feature description>`
```

## Important Notes

- **Never modify files in the source project** — this skill only reads from `~/.claude/skills/smith/` and writes to the current working directory
- **Existing files**: Always ask before overwriting. If `CLAUDE.md` exists, offer to merge or replace
- **Idempotent**: Running `/smith.init` again should detect existing setup and offer to update
- **Minimal questions**: Skip any question where codebase detection has high confidence. The goal is to confirm, not interrogate
- The generated CLAUDE.md and constitution are starting points — users should customize them for their specific needs
