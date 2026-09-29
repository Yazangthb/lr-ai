#!/usr/bin/env python3
"""LR-AI command-line entry point.

Usage: python scripts/lr.py <command> [options]   (run with --help for the command list)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lrai.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
