## Smith Context System

When the `context-loader.sh` UserPromptSubmit hook is active, Smith-aware
prompts (e.g. `/smith-bugfix`, `/smith-new`, or natural-language triggers
like "let's smith this") will arrive with an `additionalContext` block
already attached. The block contains:

- **Vault sections** — recent sessions, ledger, queue, bank, agents per
  the per-skill `context-manifest.json` config.
- **Manifest Navigator output** — `Must Read`, `Should Read`, and
  `Reference Only` file lists scoped to the task.

**Use the injected context first.** Read the Must Read files in their
entirety, focusing on the `[primary: <range>, <label>]` annotation. Treat
Should Read as supporting context. Reference Only files are for context,
not modification.

If the injection is absent (no Smith trigger detected) or carries the
"Manifest not initialized" sentinel, fall back to normal exploration:
grep, read by hypothesis, and consider running `/smith-index` to enable
structured retrieval.

## File Size Awareness

Before reading any source file over 300 lines, check its `.meta` sidecar
under `.smith/index/files/`. The sidecar lists exports, classes,
functions, and routes — enough to locate your target without a full read.
Reserve full reads of large files for the cases where the navigator's
primary annotation points there.
