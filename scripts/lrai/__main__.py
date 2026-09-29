"""`python -m lrai <command>` (with scripts/ on PYTHONPATH) works like `python scripts/lr.py <command>`."""
import sys

from .cli import main

sys.exit(main())
