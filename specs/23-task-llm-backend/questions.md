---
feature: 23-task-llm-backend
branch: 23-task-llm-backend
generated: 2026-06-03
status: ANSWERED
spec: ./spec.md
plan: ./plan.md
---

# Implementation Questions: Task-based LLM Backend

8 questions. Several were informed by the spec and plan investigations — recommendations carry the rationale.

---

## Q1: Rate-limit handling when a Task call fails

**Context:** Subscription rate-limits differ from API rate-limits. A Task spawn may fail with a rate-limit error during a bulk run. The skill needs a policy.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Exponential backoff + retry inline (5s → 10s → 20s, max 3 attempts per Task) | Self-healing; transparent to user. Bulk runs may stretch out under sustained limits. |
| B | Queue the failed file for next batch and continue | Forward progress; failures eventually retry. Risk of permanent failures if limits stay hit. |
| C | Abort the run with a clear error and let user re-run with `--resume` | Simplest; checkpoint already supports resume. User has to notice and re-invoke. |
| D | A + C — exponential retry per Task; abort the run if 3 consecutive batches all rate-limited | Combines self-healing with bail-out for systemic limits. Most robust. |

**Recommended:** **D** — per-Task exponential retry plus run-level abort on sustained limits. Maintains the Rule 4 checkpoint/resume guarantee while not silently hanging. Default to abort-on-sustained-failure since subscription quota issues usually need user attention anyway.

**Answer:** A — exponential backoff + inline retry per Task (5s → 10s → 20s, max 3 attempts). Self-healing; no run-level abort.

---

## Q2: Task spawning — parallel-in-one-block vs sequential within batch?

**Context:** The Task tool can spawn multiple sub-agents in parallel within a single tool-use block (per platform). For batch=10, the skill can either (a) emit ONE tool-use block with 10 Task calls (parallel), or (b) loop sequentially spawning 10 Tasks one at a time (serial).

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Parallel — one tool-use block with N Task calls. Faster (~10x). | Best throughput. If the platform has an undocumented block-size limit, a wholesale block may fail. Per-Task error handling is more complex. |
| B | Sequential — loop spawning one Task at a time | Slower but simpler error handling. Easier to log per-Task progress. |
| C | Parallel with fallback split — try N parallel, on wholesale-block failure retry as 2x(N/2) | Best of both. Self-heals around platform limits. More skill-prose complexity. |

**Recommended:** **C** — parallel with fallback split (per plan R2 mitigation). Default to parallel for throughput; on observed wholesale-block failure, retry as smaller parallel groups. Worst case degrades to sequential without the user having to flip a flag.

**Answer:** B — sequential spawning within each batch (one Task at a time). Simpler error handling; per-Task progress visible.

---

## Q3: Per-method vs per-file Task granularity?

**Context:** Spec brief says "one Task per file." For very method-dense files (e.g., a 500-line module with 40 methods above the threshold), one Task gets a prompt with 40 method bodies → context bloat + slower response + potentially less coherent descriptions.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | One Task per file always (per spec brief) | Simplest. Risk of prompt bloat on method-dense files. |
| B | Per-file by default; split into per-method Tasks when qualifying-methods exceed threshold (e.g., >15) | Adaptive. Same total Task count or slightly more, but each Task has a tighter prompt. |
| C | One Task per method, always | Most granular. Many small Tasks → more orchestration overhead + higher Task-spawn-rate. |

**Recommended:** **B** — per-file by default, split when methods exceed 15. Keeps the common case efficient and handles dense files without blowing prompt size. The threshold is configurable.

**Answer:** B — per-file by default; split into per-method Tasks when qualifying-methods exceed 15 (configurable threshold).

---

## Q4: Pre-flight cost transparency?

**Context:** Subscription rate limits and overall quota awareness matter even when there's no direct $ bill. A user invoking `--describe` on 1,214 files may want to know upfront roughly how many Tasks will be spawned and how long it'll take.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Yes — show pre-flight estimate: "Will spawn N Tasks (~M methods total). Estimated wall time: T minutes." User confirms before run. | Transparent. Adds one confirmation step (can be `--yes` bypassed). |
| B | No estimate — just run | Lower friction. User has no upfront sense of scope. |
| C | Estimate displayed but no confirmation gate (informational only) | Middle ground. User sees scope; run proceeds automatically. |

**Recommended:** **A** — pre-flight estimate + confirmation gate, with `--yes` to bypass. Matches the Q5 batched-approval pattern from PR #21 (per-batch approval). User keeps control over multi-hour runs.

**Answer:** A — pre-flight estimate ("N Tasks, ~M methods, ~T min") + confirmation gate. `--yes` flag bypasses.

---

## Q5: Task stub — behavior when canned response file lacks a method id?

**Context:** Plan §C1 specifies tests use `SMITH_TASK_STUB=1` env var + a canned-responses JSON file. If a test invokes the skill on a fixture that includes a method id not present in the canned file, the stub has to do something.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Fail the test loudly — fixture and canned-responses must stay in sync | Brittle but explicit; forces test-maintenance discipline. |
| B | Auto-generate a placeholder description like `"[stub:<method_id>]"` | Tolerant; tests still run but don't assert real description quality. |
| C | Skip the method (no description recorded) | Lets tests focus on orchestration without forcing canned responses for every method. |

**Recommended:** **A** — fail loud. Test brittleness here is a feature: it catches drift between fixtures and canned data, which would otherwise hide real bugs in the prompt construction.

**Answer:** A — fail loud when fixture has a method id missing from the canned-responses JSON. Drift detection > silent pass.

---

## Q6: Long-term deprecation of describe_headless.py + meta_describe.py update-touched CLI?

**Context:** v3 keeps both as headless fallbacks. Over time the user may shift entirely to interactive Smith sessions, making the headless path unused. The question is whether to mark them deprecated now (with timeline) or keep indefinitely.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Keep indefinitely — they're real fallbacks for cron/CI/headless | Useful for the 2am scheduler. Documents two-backend complexity forever. |
| B | Mark deprecated in v3 docs; plan removal for v4 | Signals intent; users with scheduled runs can migrate. Forces fewer maintenance burdens later. |
| C | Remove now — force interactive-only | Cleanest code. Breaks the 2am scheduler unless that gets refactored to use a session. |

**Recommended:** **A** — keep indefinitely as the explicit headless fallback. The 2am scheduler is a real, supported pattern. Two backends is mild complexity; removing it would require rethinking the scheduler entirely.

**Answer:** REVISED — DROP THE HEADLESS BACKEND ENTIRELY. Initial framing was based on incorrect assumption that the 2am scheduler uses direct-HTTPS LLM calls. Investigation showed the scheduler invokes `claude --print` which IS a Claude Code session — Task spawning works there too. v3 is Task-spawning only: no `describe_headless.py`, no `--llm-backend api` flag, no `CLAUDE_HEADLESS` env var. Simpler design. Depends on `claude` CLI being present (already required for the scheduler anyway). Q8 also resolved by this decision (no second backend to switch between).

---

## Q7: Model override on Task spawning — what if `subagent_type: general` doesn't accept `model: haiku-4-5`?

**Context:** Plan R1: the Task tool's `subagent_type: general` may run on the session's primary model (Sonnet/Opus) regardless of the `model` parameter. If so, description Tasks would inflate subscription cost dramatically (Opus is ~30x Haiku per token).

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Runtime probe at skill start — spawn a small test Task, parse the returned content for model hints; if NOT Haiku, abort with a clear error and fall back to api backend | Defensive. Catches the failure mode early. Adds one extra Task call per run. |
| B | Trust the model override; if it doesn't work, the user notices via subscription rate-limit errors | Simplest. Risk: user gets surprised by quota burn before noticing. |
| C | Use a different `subagent_type` known to honor model overrides (e.g., a custom `haiku-describer` subagent type registered in `.claude/agents/`) | Most reliable IF a Haiku-specific subagent type exists. Requires verifying it does. |

**Recommended:** **A** — runtime probe + abort + fallback to api. Cost-sensitive operation; "trust and burn quota" isn't a good default. The probe is one Task call (~1s) added to startup; acceptable.

**Answer:** A — runtime probe at skill start. Spawn a test Task with model=haiku-4-5; if the response indicates a different model ran, abort with clear error explaining the situation and recommending the user verify their `subagent_type`/`model` setup. Even more important now that the headless backend is dropped (no fallback path).

---

## Q8: `CLAUDE_HEADLESS=1` env var — auto-set by scheduler, or user-explicit?

**Context:** The 2am scheduler script (`scheduler/smith-scheduler.sh`) currently runs without a session. v3 needs it to trigger the headless backend.

**Options:**
| Option | Description | Implications |
|--------|-------------|--------------|
| A | Scheduler auto-sets `CLAUDE_HEADLESS=1` before invoking `/smith-index --describe` | Transparent. Scheduler "just works" after v3 ships. User never sees the env var. |
| B | User must explicitly pass `--llm-backend api` flag in scheduled invocations | Explicit. User has to remember it. Risk of forgotten flag → cron job hangs trying to spawn Tasks from no session. |
| C | Both — auto-set by scheduler AND respect explicit flag | Belt-and-suspenders. Most ergonomic. |

**Recommended:** **C** — both. Scheduler auto-sets the env var; `--llm-backend api` is the explicit override path for users running headless manually. Either signals "go through describe_headless.py."

**Answer:** N/A — RESOLVED BY Q6. No headless backend means no `CLAUDE_HEADLESS` env var, no `--llm-backend` flag. Question dropped.
