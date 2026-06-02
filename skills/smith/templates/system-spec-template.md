---
system: system-<NN>-<short-kebab-name>
status: draft
paths:
  - <relative-prefix>/
also_affects: []
---

<!--
  IMPORTANT — The YAML frontmatter block above MUST stay valid (lint-able)
  for the Smith manifest resolver tier 1 to bucket files into this system.

  Required field:
    system          — Identifier. MUST match this file's parent directory name
                      (.specify/systems/<id>/ → <id>). Accepted forms:
                      `system-NN-short-name` or `system-short-name`.

  Recommended:
    paths           — List of literal directory prefixes (project-relative,
                      POSIX, ending in `/`) that belong to this system.
                      Resolver tier 1 walks these in longest-prefix-first
                      order. NO glob characters (*, ?, [], {}, !) in v1 —
                      literal prefixes only. May be empty (system contributes
                      nothing to tier 1; tier 2/3 still resolve files).
    status          — One of: draft, in-progress, complete, active,
                      deprecated, proposed.
    also_affects    — Optional cross-system pointer list. Each entry
                      references another system by id. Informational only —
                      does NOT extend tier-1 path coverage.

  The body below the closing `---` is unconstrained markdown — replace the
  placeholders with prose describing this system. Free-form additions are
  fine; the resolver only reads the frontmatter.
-->

# Feature Specification: <System Human Name>

**System ID**: `system-<NN>-<short-kebab-name>`
**Created**: <YYYY-MM-DD>
**Status**: Draft

## Purpose

<One paragraph summary of this system's primary responsibility and the
problem it solves. Aim for two to four sentences. The first sentence should
make sense out of context.>

## User Scenarios & Testing

<!--
  Describe the user journeys this system supports. Each scenario should be
  independently testable.
-->

### Scenario 1 — <Brief Title>

<Plain-language description of the journey>

**Acceptance**:

1. **Given** <initial state>, **When** <action>, **Then** <expected outcome>
2. **Given** <initial state>, **When** <action>, **Then** <expected outcome>

### Edge Cases

- What happens when <boundary condition>?
- How does this system handle <error scenario>?

## Functional Requirements

- **FR-1**: <Concrete capability this system provides>
- **FR-2**: <Concrete capability this system provides>
- **FR-3**: <Concrete capability this system provides>

## Files & Components

<Bulleted list of significant entry points (modules, services, packages).
These are informational — the machine-read source of truth is the `paths:`
field in the YAML frontmatter above.>

- `<relative-prefix>/<entry-point>` — <one-line description>

## Interfaces

<Public APIs, IPC contracts, message buses, exported modules. Describe what
other systems can call into this one with.>

## Dependencies

<List of other systems this one consumes. When this list grows, mirror
significant cross-cutting touchpoints into `also_affects` in the frontmatter
so they show up in cross-system tooling.>

- `system-<id>` — <why this system is consumed>

## Success Criteria

<Measurable conditions for considering this system healthy/complete.
Examples: latency targets, throughput, error budgets, coverage thresholds.>

- **SC-1**: <Quantitative or qualitative criterion>
- **SC-2**: <Quantitative or qualitative criterion>
