# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.x (latest) | Yes |

Only the latest release receives security updates. We recommend staying on the most recent version.

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Email **tech@attck.com** with the subject line: `Smith Security: <brief description>`

Include:

- Description of the vulnerability
- Steps to reproduce
- Affected files or components (skills, hooks, installer, scheduler)
- Potential impact
- Suggested fix (if you have one)

## Response Timeline

- **Acknowledge:** within 48 hours
- **Assess:** within 7 days
- **Fix or mitigate:** within 30 days for critical issues

## Scope

This policy covers:

- Smith skills (`skills/`)
- Hooks (`hooks/`)
- Installer and uninstaller (`scripts/`)
- Scheduler (`scheduler/`)
- Settings fragment (`settings/`)

This policy does **not** cover:

- Claude Code itself (report to [Anthropic](https://www.anthropic.com/))
- Third-party dependencies (Playwright, jq, gh CLI)
- Per-project vault data (`.smith/vault/`)

## Credit

Security reporters will be credited in the CHANGELOG unless they prefer to remain anonymous. Let us know your preference when reporting.

## Disclosure

We follow coordinated disclosure. We will work with you on a timeline for public disclosure after a fix is available.
