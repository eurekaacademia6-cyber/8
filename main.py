from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from worker_runtime import run_worker


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(
        "Quotex Vision AI"
    )
    app.setApplicationDisplayName(
        "Quotex Vision AI - Continuous Live"
    )

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        run_worker()
    else:
        raise SystemExit(main())
