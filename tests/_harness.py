"""Test harness: put hooks/ on sys.path so tests can import workflow_summary_lib."""

import os
import sys

HOOKS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks"))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))
