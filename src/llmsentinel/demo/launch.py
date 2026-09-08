"""Console entry point for the Streamlit demo (``llmsentinel-demo``)."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    from streamlit.web import cli as stcli

    app = Path(__file__).resolve().parent / "app.py"
    sys.argv = ["streamlit", "run", str(app), "--server.port", "8601"]
    return int(stcli.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
