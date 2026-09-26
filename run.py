"""Start the Pin Catalog Builder web interface.

Usage:
    python run.py

Then open http://127.0.0.1:8000 in your browser (it opens automatically).
"""

from __future__ import annotations

import sys
import threading
import webbrowser

if sys.version_info < (3, 12):
    sys.exit("Pin Catalog Builder needs Python 3.12 or newer. You are running " + sys.version.split()[0])

import uvicorn

from app.config import get_settings
from app.main import create_app, setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    app = create_app(settings)
    url = f"http://{settings.HOST}:{settings.PORT}"
    print(f"\n  Pin Catalog Builder is running at {url}\n  Press Ctrl+C to stop.\n")
    if settings.OPEN_BROWSER:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, log_level="warning")


if __name__ == "__main__":
    main()
