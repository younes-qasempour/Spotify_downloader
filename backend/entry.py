"""
Frozen PyInstaller entry point for the Flacify v2.0 FastAPI backend sidecar.
"""

import multiprocessing
import os
import sys


def _ensure_std_streams() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    _ensure_std_streams()
    from backend.__main__ import main

    main()
