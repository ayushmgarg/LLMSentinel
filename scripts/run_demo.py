"""Launch the Streamlit demo. Thin wrapper so it has a stable command.

    python scripts/run_demo.py       # opens the local demo at http://localhost:8601
"""

from __future__ import annotations

import sys
from pathlib import Path

from streamlit.web import cli as stcli

APP = Path(__file__).resolve().parent.parent / "src" / "llmsentinel" / "demo" / "app.py"


def main() -> int:
    sys.argv = ["streamlit", "run", str(APP), "--server.port", "8601"]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
