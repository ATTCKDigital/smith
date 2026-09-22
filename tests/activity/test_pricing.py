"""hooks/pricing.json and the two ways it fails silently (T064 / T069).

Split from ``test_usage.py`` on the 500-line decompose rule. Everything here
is about the pricing TABLE; ``test_usage.py`` covers what consumes it.

Both failure modes below render a plausible number rather than an error, which
is what makes them worth an executable guard:

1. **A raw ``json.load``** produces a dict that looks complete and matches
   nothing. ``match_family()`` reads ``_compiled_patterns``, which only
   ``load_pricing()`` injects, through ``.get(…) or []`` — so the miss is a
   quiet ``None``, not a ``KeyError``, and USD simply stops appearing.
2. **A misordered family.** ``match_family()`` returns the FIRST array-order
   match and every pattern is a prefix glob, so `claude-opus-5*` placed above
   `claude-opus-5-5*` bills Opus 5.5 at 5/25 instead of 4/20 — a 25%
   overstatement indistinguishable from a real figure at runtime.

Rates are transcribed, never derived: cache read is 0.1x base input for most
families but **0.025x** for Fable 5.1 / Mythos 5.1 and **0.05x** for Opus 5.5.
A derived table would price Fable 5.1 cache reads 4x too high.

Reached from CI through the flat tests/smith-activity.test.sh wrapper.
"""

import ast
import json
import os
import unittest

from tests._harness import *  # noqa: F401,F403 — puts scripts/activity on sys.path

import usage as U

PRICING = os.path.join(REPO_ROOT, "hooks", "pricing.json")
ACTIVITY_SRC = os.path.join(REPO_ROOT, "scripts", "activity")


class PricingTableTest(unittest.TestCase):
    def setUp(self):
        U.reset_pricing_cache()
        self.table = U.load_pricing(PRICING)
        self.assertIsNotNone(self.table, "hooks/pricing.json must load")
        self.families = [m["family"] for m in self.table["models"]]

    def test_running_model_resolves(self):
        # The defect FR-62 exists for: before claude-opus-5* was added,
        # match_family() returned None for every live session and the
        # Stop-hook summary silently omitted its USD line.
        for model in ("claude-opus-5", "claude-opus-5[1m]", "claude-opus-5-20260601"):
            self.assertIsNotNone(U.rates_for(model, self.table), model)

    def test_specificity_ordering_for_every_prefix_pair(self):
        """The guard that stops a future edit silently repricing a minor."""
        stems = [(f, f[:-1] if f.endswith("*") else f) for f in self.families]
        pairs = 0
        for i, (family, stem) in enumerate(stems):
            for j, (other, other_stem) in enumerate(stems):
                if i == j or not other_stem.startswith(stem):
                    continue
                pairs += 1
                self.assertLess(
                    j,
                    i,
                    "%s is more specific than %s and must appear FIRST — "
                    "match_family() takes the first array-order match"
                    % (other, family),
                )
        # A pass with zero pairs compared would prove nothing at all.
        self.assertGreater(pairs, 0, "no prefix pairs found — assertion is vacuous")

    def test_specific_families_are_not_swallowed(self):
        """The ordering rule restated as the outcome it protects."""
        cases = [
            ("claude-opus-5-5", 4.0, 20.0, 0.2),
            ("claude-opus-5", 5.0, 25.0, 0.5),
            ("claude-fable-5-1", 10.0, 50.0, 0.25),
            ("claude-fable-5", 10.0, 50.0, 1.0),
            ("claude-mythos-5-1", 10.0, 50.0, 0.25),
            ("claude-mythos-5", 10.0, 50.0, 1.0),
            ("claude-opus-4-8", 5.0, 25.0, 0.5),
            ("claude-opus-4-7", 5.0, 25.0, 0.5),
            ("claude-opus-4", 15.0, 75.0, 1.5),
            ("claude-sonnet-5", 2.0, 10.0, 0.2),
        ]
        for model, inp, out, cache_read in cases:
            rates = U.rates_for(model, self.table)
            self.assertIsNotNone(rates, model)
            self.assertEqual(rates["input_per_mtok"], inp, model)
            self.assertEqual(rates["output_per_mtok"], out, model)
            self.assertEqual(rates["cache_read_per_mtok"], cache_read, model)

    def test_nonexistent_family_resolves_to_none(self):
        self.assertIsNone(U.rates_for("claude-notashipped-7", self.table))
        self.assertIsNone(U.rates_for(None, self.table))

    def test_every_family_carries_provenance(self):
        """A fabricated rate is indistinguishable from a real one at runtime,
        so the guard sits on the metadata rather than on the number."""
        for entry in self.table["models"]:
            self.assertTrue(entry.get("last_verified"), entry.get("family"))
            self.assertTrue(entry.get("source_url"), entry.get("family"))

    def test_no_numeric_rate_without_provenance(self):
        with open(PRICING, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        for entry in raw["models"]:
            numeric = [
                key
                for key in (
                    "input_per_mtok",
                    "output_per_mtok",
                    "cache_write_5m_per_mtok",
                    "cache_read_per_mtok",
                )
                if isinstance(entry.get(key), (int, float))
            ]
            if numeric:
                self.assertTrue(
                    entry.get("last_verified"),
                    "%s carries rates %s with no last_verified"
                    % (entry.get("family"), numeric),
                )

    def test_preserved_top_level_keys(self):
        self.assertIn("$comment", self.table)
        self.assertIn("fallback_order", self.table)


class ContractTrapTest(unittest.TestCase):
    """FR-33's trap, in executable form (T069)."""

    def setUp(self):
        U.reset_pricing_cache()

    def test_raw_json_load_resolves_every_model_to_none(self):
        with open(PRICING, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        # The dict is complete by every visible measure...
        self.assertEqual(len(raw["models"]), len(U.load_pricing(PRICING)["models"]))
        self.assertIn("claude-opus-5*", [m["family"] for m in raw["models"]])
        # ...and resolves nothing, silently.
        for model in ("claude-opus-5", "claude-sonnet-4-6", "claude-haiku-3-5"):
            self.assertIsNone(U.rates_for(model, raw), model)
        self.assertNotIn("_compiled_patterns", raw)
        # And it does so without raising, which is the whole problem.
        self.assertIsNone(U.rates_for("claude-opus-5", raw))

    def test_load_pricing_injects_the_key_match_family_needs(self):
        table = U.load_pricing(PRICING)
        self.assertIn("_compiled_patterns", table)
        self.assertEqual(len(table["_compiled_patterns"]), len(table["models"]))

    def test_no_module_parses_pricing_json_independently(self):
        """No file under scripts/activity/ may open or json.load the table.

        Walked as an AST rather than grepped: this module's own docstring
        names ``json.load()`` and ``pricing.json`` in the same sentence while
        warning against exactly that combination, and a line-oriented grep
        cannot tell the warning from the offence.
        """

        def is_parse_call(node):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                return True
            return (
                isinstance(func, ast.Attribute)
                and func.attr in ("load", "loads")
                and isinstance(func.value, ast.Name)
                and func.value.id == "json"
            )

        offenders = []
        for name in sorted(os.listdir(ACTIVITY_SRC)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(ACTIVITY_SRC, name)
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
            tree = ast.parse(source, filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and is_parse_call(node):
                    segment = ast.get_source_segment(source, node) or ""
                    if "pricing" in segment:
                        offenders.append("%s:%d %s" % (name, node.lineno, segment))
                # A literal path is the easy case. The one that actually
                # occurred during review was `json.load(open(path))` inside
                # load_pricing() itself, where no literal names the file — so
                # any pricing-named function is checked by enclosing scope too.
                if isinstance(node, ast.FunctionDef) and "pricing" in node.name:
                    for inner in ast.walk(node):
                        if isinstance(inner, ast.Call) and is_parse_call(inner):
                            offenders.append(
                                "%s:%d %s (inside %s)"
                                % (
                                    name,
                                    inner.lineno,
                                    ast.get_source_segment(source, inner),
                                    node.name,
                                )
                            )
        self.assertEqual(offenders, [], "pricing.json must only reach load_pricing()")

    def test_usage_obtains_rates_only_through_the_lib(self):
        with open(os.path.join(ACTIVITY_SRC, "usage.py"), "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("W.load_pricing(", source)
        self.assertIn("W.match_family(", source)

    def test_missing_file_loads_as_none_not_as_empty(self):
        self.assertIsNone(U.load_pricing("/nonexistent/pricing.json"))


class PricingCacheTest(unittest.TestCase):
    """T059's throttle: one load at startup, mtime-gated refresh ≤ once/60 s."""

    def setUp(self):
        U.reset_pricing_cache()

    def test_repeated_loads_inside_the_window_reuse_the_table(self):
        first = U.load_pricing(PRICING, now=1000.0)
        second = U.load_pricing(PRICING, now=1000.5)
        self.assertIs(first, second)

    def test_refresh_after_the_window_still_returns_a_valid_table(self):
        first = U.load_pricing(PRICING, now=1000.0)
        later = U.load_pricing(PRICING, now=1000.0 + U.PRICING_REFRESH_S + 1)
        self.assertIsNotNone(later)
        # Unchanged mtime ⇒ no re-parse, so the same object comes back.
        self.assertIs(first, later)


if __name__ == "__main__":
    unittest.main()
