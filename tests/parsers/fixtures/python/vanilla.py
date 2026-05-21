"""Vanilla module with a couple of plain functions."""

import os
import sys


def add(a, b):
    """Add two numbers."""
    return a + b


def greet(name):
    """Say hello.

    Second line.
    """
    return f"Hello, {name}"


def _private():
    return 1


# Keep imports alive for the parser test.
_USED = (os.path.sep, sys.platform)
