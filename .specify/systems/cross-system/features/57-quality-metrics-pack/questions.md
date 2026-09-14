# Implementation Questions: Quality Metrics Pack

**Generated**: 2026-09-14
**Feature**: [spec.md](./spec.md)
**Plan**: [plan.md](./plan.md)
**Status**: ANSWERED

> All five answers accepted via the user's standing delegation ("continue
> all the way through all of them with as little feedback from me as
> possible" — auto-accept recommended answers, recorded here for the audit
> trail). Each recommendation is evidence-backed in the pre-feature
> exploration report.

---

## Q1: Generalize §3.1/§5.3 in place, or add a new parallel step?
**Options**: A) Generalize `smith-build` §3.1 and `smith-bugfix` §5.3 IN
PLACE — config-driven (`quality.test`/`quality.lint`), with the CURRENT
hardcoded bullet list preserved verbatim as the fallback when the config
key is absent (zero behavior change for any project not yet configuring
`quality`). B) Leave the hardcoded bullets untouched and add an entirely
new, separate "Quality Gate" step/phase that duplicates test/lint
execution alongside them — two code paths for the same concern, doubling
maintenance surface and leaving the Armory-shaped leftover in place
instead of retiring it.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q2: `quality` config key shape?
**Options**: A) A NEW top-level `quality` key in `.smith/config.json` —
`{ test[], lint[], typecheck[], coverage{command, minimum_percent, regex},
function_length{soft, decompose}, timeout_seconds:120, excludes[] }` — a
sibling to `security_review`/`supply_chain`, not nested under either. B)
Nest quality settings under an existing key (e.g. `security_review`) —
quality metrics are not security-review-shaped, and `security_review`'s
own schema is closed per feature 55's FR-24, so nesting would misrepresent
what this feature's settings control.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q3: Function-length two-tier thresholds?
**Options**: A) 50-line soft threshold / 100-line decompose threshold,
both `quality.function_length`-overridable — mirrors the constitution's
File Size Policy soft/decompose shape at function-body granularity instead
of file granularity, and folds soft-tier hits into a count rather than
listing each individually (this pipeline's existing low-severity-folding
convention). B) A single flat threshold with no tiering — simpler, but
loses the "worth a look" vs. "should decompose" distinction and produces
noisier PRs with no folding for near-threshold hits.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q4: Coverage-percent parsing strategy?
**Options**: A) A built-in regex catalogue covering pytest-cov, jest/
istanbul (`text-summary`), and `go test -cover` output shapes, tried in a
fixed order, with `quality.coverage.regex` as a full override tried first
when configured; output matching neither is disclosed as unparsed and
never fails the build. B) Require every project to supply its own regex
up front, with no built-in catalogue — raises the adoption bar for the
three most common stacks this pipeline's own consuming projects already
use, for no accuracy gain.
**Recommended**: A.
**Answer**: A (accepted via delegation).

## Q5: Workflow scope — which skills gain which pieces?
**Options**: A) `smith-build` gets the full pack (generalized §3.1 Testing
+ new §3.1b Lint + §3.1c Typecheck + §3.4 Coverage Check + §5.3.2
Function-Length Scan + two new PR sections); `smith-bugfix` gets ONLY the
§5.3 Lint generalization (stays intentionally lightweight, matching
features 55/56's own bugfix-exclusion precedent for their heavier passes);
`smith-implement` gets none of this feature — it has no independent PR/
commit step of its own to attach an advisory to, and runs only inside an
active top-level workflow whose own pipeline (or lack thereof) already
determines what runs. B) Full parity across all three — `smith-implement`
isn't a self-contained pipeline, so duplicating checks there would either
be inert or double-run against code the caller's own pipeline already
checks; rejected on that basis.
**Recommended**: A.
**Answer**: A (accepted via delegation).

---

Plan-level mechanical resolutions (not gate matters, recorded):
`quality.excludes` added to the schema for symmetry with `security_review.
excludes`/`supply_chain.excludes`, defaulting to `[]` (no additional
excludes beyond §5.3/§5.3.1's own built-in list); `quality.coverage.
command`/`minimum_percent`/`regex` all default to `null` (coverage check
skipped entirely absent a configured command); `python3 subprocess.run(...,
timeout=N)` reused verbatim from feature 56 rather than a shell `timeout`/
`gtimeout` wrapper (both confirmed absent on the reference dev machine);
new PR-body sections ("Function Length Warnings", "Quality Metrics") both
appended after "Supply-Chain Review" and before "Release notes", in that
relative order, per the existing append-after-the-newest-section
convention.
