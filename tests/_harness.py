"""Test harness: put hooks/ and scripts/activity/ on sys.path.

Consumers do ``from tests._harness import *``, so everything below is
deliberately module-level and additive — the five existing ``tests/test_*.py``
files pin ``workflow_summary_lib``'s behavior and must keep passing unchanged.
"""

import os
import sys

HOOKS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "hooks"))
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))

# --- /smith-activity (feature 60) ------------------------------------------
# Same pattern as HOOKS_DIR/FIXTURES_DIR above so tests/activity/test_*.py can
# ``import phases`` / ``import paths`` directly rather than reaching across the
# tree. scripts/activity/ is appended rather than prepended: hooks/ keeps
# precedence, so nothing here can shadow workflow_summary_lib.
ACTIVITY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts", "activity")
)
if ACTIVITY_DIR not in sys.path:
    sys.path.append(ACTIVITY_DIR)

ACTIVITY_FIXTURES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "activity", "fixtures")
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
