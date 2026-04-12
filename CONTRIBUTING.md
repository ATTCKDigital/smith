# Contributing to Smith

Thank you for your interest in Smith! This document explains how to contribute
to the project effectively.

Smith is maintained by [ATTCK](https://attck.com) and released under the MIT
license. We welcome bug reports, feature requests, and ideas from everyone.
Pull requests are by invitation only (details below).

---

## Issues and Bug Reports

Anyone can open an issue. Good bug reports make fixes happen faster.

Please include:

- **Claude Code version** (`claude --version`)
- **Operating system** and version (e.g., macOS 15.3, Ubuntu 24.04)
- **Smith version** (check your installed skill files or `git log --oneline -1`)
- **Description** of the problem
- **Steps to reproduce** — the more specific, the better
- **Expected behavior** — what you thought would happen
- **Actual behavior** — what actually happened
- **Relevant logs or error output** — redact any credentials or personal information

If the issue is intermittent, note the frequency and any patterns you have
observed.

## Feature Requests

Feature requests are welcome as GitHub Issues. When describing a feature:

- **Focus on the use case**, not just the solution. Tell us what you are trying
  to accomplish and why the current behavior falls short.
- Describe the workflow or scenario where the feature would help.
- If you have a proposed approach, include it — but the use case matters more.
- Check existing issues first to avoid duplicates. Add a comment to an existing
  issue if your use case is related.

## Pull Requests — By Invitation

Pull requests are **by invitation only**. Here is how it works:

1. **Open an issue first.** Describe the bug fix, improvement, or new skill you
   have in mind.
2. **Discuss with maintainers.** We will evaluate the proposal and may ask
   clarifying questions.
3. **Receive an invitation.** If the change aligns with the project direction, a
   maintainer will invite you to submit a PR.
4. **Submit your PR.** Follow the guidelines below.

This process ensures that contributors do not invest time on changes that may
not be merged. It also keeps the project focused and maintainable.

### If You Are Invited to Submit a PR

1. **Fork the repository** and create a feature branch from `main`.
   Use a descriptive branch name (e.g., `feat/skill-name` or `fix/hook-issue`).

2. **Follow existing SKILL.md conventions.** Every skill file uses YAML
   frontmatter with the following fields:
   - `name` — short, lowercase, hyphenated
   - `description` — one-line summary
   - Any other fields used by existing skills (check a few for reference)

3. **Update CHANGELOG.md.** Add your change under the `[Unreleased]` section
   using the appropriate category (Added, Changed, Fixed, Removed).

4. **Test `install.sh` locally.** Run the installer on your machine and verify
   that your changes work end-to-end. Uninstall and reinstall to check for
   regressions.

5. **One skill per PR** unless the skills are tightly coupled and must ship
   together. Smaller PRs are easier to review and merge.

6. **Write a clear PR description.** Explain what the change does, why it is
   needed, and how you tested it. Reference the issue number.

---

## Coding Conventions

### Skills

- Skills are **Markdown files with YAML frontmatter**.
- Keep instructions clear and unambiguous. Claude Code interprets these
  literally.
- Use consistent formatting with existing skills.
- Do not assume a specific working directory structure beyond what Smith
  itself creates.

### Hooks

- Hooks are **POSIX-ish Bash scripts** (`#!/usr/bin/env bash`).
- They must run on macOS and common Linux distributions.
- Keep hooks focused — one responsibility per hook.
- Use `set -euo pipefail` at the top of each hook.

### General Rules

- **No hardcoded absolute paths.** Use `$HOME`, `$SMITH_DIR`, or other
  environment variables. Paths like `/Users/someone/...` must never appear.
- **No credentials or PII** in any file, ever. Not in examples, not in
  comments, not in test fixtures.
- **No unnecessary dependencies.** If a hook needs a tool, check for it and
  fail gracefully with a clear message.
- **Keep it simple.** Prefer clarity over cleverness.

---

## Development Setup

1. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/smith.git
   cd smith
   ```

2. Run the installer to set up skills and hooks locally:
   ```bash
   ./install.sh
   ```

3. Make your changes and test them with Claude Code.

4. Before submitting, verify:
   - The installer runs without errors
   - Your changes do not break existing skills or hooks
   - CHANGELOG.md is updated

---

## Communication

All project communication happens through **GitHub Issues**. This keeps
discussions searchable and linked to the relevant context.

For security issues, see [SECURITY.md](SECURITY.md) — do not use public issues
for vulnerability reports.

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you agree to uphold its standards.

---

## License

By contributing to Smith, you agree that your contributions will be licensed
under the [MIT License](LICENSE) that covers the project.

---

Thank you for helping make Smith better.
