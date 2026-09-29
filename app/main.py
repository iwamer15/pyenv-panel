"""エントリポイント。

実行例:
    python -m app.main            # GUI起動（端末モード/管理者モード）
    python -m app.main check      # ヘッドレス自己診断（タスクスケジューラ向け。GUIは開かない）
    python -m app.main check --sync

    PyInstallerでビルドした exe も同様に `PyEnvPanel.exe check` で
    ヘッドレス実行できる（app/cli.py 参照）。

環境変数（開発・動作確認用）:
    PYENV_PANEL_RUNTIME_ROOT   共有ランタイムのルート（既定: sample_runtime/ または UNCパス）
    PYENV_PANEL_TARGET_PYTHON  管理対象のpython実行ファイルパス（既定: PATH上のpython）
"""
from __future__ import annotations

import sys

from . import cli
from .config import resolve_runtime_root, resolve_target_python


def main() -> int:
    # サブコマンド（例: "check"）が指定された場合はGUIを起動せず、
    # app.cli にそのまま委譲する（タスクスケジューラ等の無人実行向け）。
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        return cli.main(sys.argv[1:])

    # 遅延import: ヘッドレス実行時にPySide6のQApplication初期化コストや
    # プラットフォームプラグイン依存を避けるため、GUIモードでのみ読み込む。
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    from .ui.theme import APP_QSS

    app = QApplication(sys.argv)
    app.setStyle("Fusion")   # OSごとの見た目の差をなくし、スタイルシートを確実に効かせる
    if sys.platform == "win32":
        app.setFont(QFont("Yu Gothic UI", 10))
    app.setStyleSheet(APP_QSS)

    paths = resolve_runtime_root()
    target_python = resolve_target_python()

    window = MainWindow(paths, target_python)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
