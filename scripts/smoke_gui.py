from __future__ import annotations

import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from reportgen.gui.app import MainWindow


def main() -> int:
    # Skip network-backed model refresh during the GUI smoke test.
    os.environ.pop("OPENAI_API_KEY", None)
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    QTimer.singleShot(300, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
