"""エントリポイント。

実行例:
    python -m app.main

環境変数（開発・動作確認用）:
    PYENV_PANEL_RUNTIME_ROOT   共有ランタイムのルート（既定: sample_runtime/ または UNCパス）
    PYENV_PANEL_TARGET_PYTHON  管理対象のpython実行ファイルパス（既定: PATH上のpython）
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .config import resolve_runtime_root, resolve_target_python
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)

    paths = resolve_runtime_root()
    target_python = resolve_target_python()

    window = MainWindow(paths, target_python)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
