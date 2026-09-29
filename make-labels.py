#!/usr/bin/env python3

import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
venv_root = root / ".venv"
venv_python = venv_root / "bin" / "python"

if venv_python.is_file() and Path(sys.prefix).resolve() != venv_root.resolve():
    os.execv(venv_python, [str(venv_python), str(root / "make-labels.py"), *sys.argv[1:]])

sys.path.insert(0, str(root))
from labels.cli import run

if __name__ == "__main__":
    run()
