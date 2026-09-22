"""Stage a replay fixture into a temp directory and load it (T031/T043/T049).

Named with a leading underscore so ``unittest discover`` (which matches
``test*.py``) never collects it as a suite.

Three jobs, and nothing else:

1. **Substitute ``@FIXTURE@``** with the staging directory, so markers carry
   real absolute ``worktree:`` / ``session_log:`` paths and
   ``markers.read_marker`` runs unmodified rather than being imitated here. A
   test-local marker parser would be testing itself.
2. **Build the FR-58 ingest order.** Session-log records get
   ``seq = 10 * (index + 1)``; a hook event names the record it follows with
   ``"after"`` and gets that record's ``seq`` plus a small offset. No fixture
   hard-codes a sequence number, and no parsed ``[HH:MM:SS]`` stamp is read.
3. **Synthesize ``at``**, the daemon's own ingest timestamp, from ``seq``.
   ``at`` is the only timestamp the resolver may read; ``timestamp_text`` and
   its ``clock`` label ride along untouched for a renderer to print.

Python 3.8, stdlib only.
"""

import json
import os
import shutil
import tempfile

from tests._harness import *  # noqa: F401,F403 -- puts scripts/activity on sys.path

import markers as M
import phases as P
import sessionlog as SL

SEQ_STEP = 10
TOKEN = "@FIXTURE@"


def _at_for(seq):
    """A synthetic daemon ingest stamp. Monotonic in ``seq`` by construction."""
    return "2026-09-22T16:%02d:%02dZ" % ((seq // 60) % 60, seq % 60)


def _substitute(text, root):
    return text.replace(TOKEN, root)


class Fixture(object):
    """One staged fixture: markers, ordered records, ordered events."""

    def __init__(self, name, artifacts=None):
        self.name = name
        self.source = os.path.join(ACTIVITY_FIXTURES_DIR, name)
        self.root = tempfile.mkdtemp(prefix="smith-activity-fx-")
        self.primary = os.path.join(self.root, "primary")
        self.markers = []
        self.records = []
        self.events = []
        self._stage(artifacts)

    # -- staging ---------------------------------------------------------

    def _stage(self, artifacts):
        os.makedirs(self.primary, exist_ok=True)
        log_source = os.path.join(self.source, "session-log.md")
        self.session_log = os.path.join(self.root, "session-log.md")
        with open(log_source, "r", encoding="utf-8") as fh:
            text = _substitute(fh.read(), self.root)
        with open(self.session_log, "w", encoding="utf-8") as fh:
            fh.write(text)

        # The primary vault's .current-session pointer. A worktree marker's
        # session_log: is EMPTY (there is no .current-session in a worktree),
        # and markers.read_marker falls back to this -- the exact shape
        # binding constraint 10 describes.
        vault = os.path.join(self.primary, ".smith", "vault")
        os.makedirs(vault, exist_ok=True)
        with open(os.path.join(vault, ".current-session"), "w") as fh:
            fh.write(self.session_log)

        self._stage_markers()
        if artifacts:
            self._stage_artifacts(artifacts)
        self._load_records()
        self._load_events()

    def _stage_markers(self):
        marker_dir = os.path.join(self.source, "markers")
        if not os.path.isdir(marker_dir):
            return
        for name in sorted(os.listdir(marker_dir)):
            if not name.endswith(".yaml"):
                continue
            with open(os.path.join(marker_dir, name), "r", encoding="utf-8") as fh:
                text = _substitute(fh.read(), self.root)
            # Convention: a marker file whose basename starts with "worktree"
            # is staged into the WORKTREE's vault, everything else into the
            # primary repo's. That is what puts a smith-new and a smith-build
            # marker for one branch into two different vaults.
            fields = M.parse_marker_text(text)
            if name.startswith("worktree"):
                vault_root = fields.get("worktree") or os.path.join(
                    self.root, "worktree"
                )
            else:
                vault_root = self.primary
            os.makedirs(vault_root, exist_ok=True)
            active = os.path.join(vault_root, ".smith", "vault", "active-workflows")
            os.makedirs(active, exist_ok=True)
            filename = M.marker_filename_for_branch(fields.get("branch") or "")
            path = os.path.join(active, filename)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            record = M.read_marker(
                path, primary_repo_path=self.primary, vault_root=vault_root
            )
            self.markers.append(record)
        self.markers.sort(key=lambda r: (not r["is_primary_vault"], r["marker_path"]))

    def _stage_artifacts(self, artifacts):
        """Copy ``artifacts/<variant>/`` into the staged worktree, both layouts
        supported by putting it where FR-12's systems layout expects it."""
        source = os.path.join(self.source, "artifacts", artifacts)
        if not os.path.isdir(source):
            raise AssertionError("no artifact variant %r in %s" % (artifacts, source))
        for marker in self.markers:
            worktree = marker.get("worktree")
            if not worktree:
                continue
            target = os.path.join(
                worktree,
                ".specify",
                "systems",
                "cross-system",
                "features",
                "60-" + (marker.get("slug") or "feature"),
            )
            if os.path.isdir(target):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copytree(source, target)

    # -- streams ---------------------------------------------------------

    def _load_records(self):
        with open(self.session_log, "r", encoding="utf-8") as fh:
            self.records = SL.parse_session_log(fh.read())
        P.sequence_records(self.records, step=SEQ_STEP)
        for record in self.records:
            record["at"] = _at_for(record["seq"])
            record["session_log"] = self.session_log

    def _load_events(self):
        path = os.path.join(self.source, "events.json")
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.loads(_substitute(fh.read(), self.root))
        used = {}
        for entry in raw:
            after = entry.pop("after", None)
            anchor = self._record_named(after) if after else None
            base = anchor["seq"] if anchor else 0
            used[base] = used.get(base, 0) + 1
            entry["seq"] = base + used[base]
            # The daemon stamps an event at INGEST, so its `timestamp` has to
            # sit on the same axis as the log records' synthesized `at` or the
            # FR-22 window would compare two unrelated clocks -- the very bug
            # FR-58 exists to prevent. The literal value from events.json is
            # kept as `timestamp_declared` for readability of the fixture.
            entry["timestamp_declared"] = entry.get("timestamp")
            entry["timestamp"] = _at_for(entry["seq"])
            entry.setdefault("session_log", self.session_log)
            self.events.append(entry)
        self.events.sort(key=lambda e: e["seq"])

    def _record_named(self, needle):
        for record in self.records:
            haystack = " ".join(
                str(record.get(key) or "")
                for key in ("description", "heading", "skill", "branch")
            )
            if needle in haystack:
                return record
        raise AssertionError("no session-log record matching %r" % needle)

    # -- checkpoints -----------------------------------------------------

    def upto(self, needle=None):
        """The two streams truncated at (and including) the named record.

        A checkpoint is a cut in the merged ingest order, so both streams are
        sliced on the same ``seq`` bound -- never on two independent indexes,
        which would let an event from the future leak into a past checkpoint.
        """
        if needle is None:
            return list(self.records), list(self.events)
        bound = self._record_named(needle)["seq"]
        # Events attached to a record sit at `seq + 1 .. seq + SEQ_STEP - 1`,
        # so an inclusive checkpoint has to reach to just before the NEXT
        # record. Cutting both streams at `bound` exactly would silently drop
        # the very event the checkpoint is about.
        return (
            [r for r in self.records if r["seq"] <= bound],
            [e for e in self.events if e["seq"] < bound + SEQ_STEP],
        )

    def marker(self, workflow_type):
        for record in self.markers:
            if record.get("workflow_type") == workflow_type:
                return record
        raise AssertionError("no %s marker in fixture %s" % (workflow_type, self.name))

    def marker_by_branch(self, branch):
        for record in self.markers:
            if record.get("branch") == branch:
                return record
        raise AssertionError("no marker for branch %s" % branch)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)
