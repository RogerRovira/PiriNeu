import sys
from pathlib import Path

# Modules live flat at the repo root (solo project, no package) — make them
# importable no matter where pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
