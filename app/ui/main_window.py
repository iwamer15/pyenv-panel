"""端末モード / ツール別ライブラリ / 管理者モードを同一ウィンドウ内で切り替えるメインウィンドウ。"""
from __future__ import annotations

from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QToolBar

from ..config import RuntimePaths
from .admin_view import AdminView
from .terminal_view import TerminalView
from .tools_view import ToolsView


class MainWindow(QMainWindow):
    def __init__(self, paths: RuntimePaths, target_python: str, group: str = "default"):
        super().__init__()
        self.setWindowTitle("Python環境統一管理ツール（プロトタイプ）")
        self.resize(1100, 680)

        self.terminal_view = TerminalView(paths, target_python, group=group)
        # 端末モードでPython本体を入れ直すと対象Pythonが切り替わるため、常に最新値を参照する
        self.tools_view = ToolsView(paths, lambda: self.terminal_view.target_python)
        self.admin_view = AdminView(paths)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.terminal_view)
        self.stack.addWidget(self.tools_view)
        self.stack.addWidget(self.admin_view)
        self.setCentralWidget(self.stack)

        self._build_toolbar()
        self.statusBar().showMessage(f"共有ランタイム: {paths.root}")

    def _build_toolbar(self):
        toolbar = QToolBar("モード切替")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        group = QActionGroup(self)
        group.setExclusive(True)

        def add_mode(label: str, show):
            action = toolbar.addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(show)
            return action

        def show_terminal():
            self.stack.setCurrentWidget(self.terminal_view)

        def show_tools():
            self.stack.setCurrentWidget(self.tools_view)
            self.tools_view.ensure_loaded()

        def show_admin():
            self.stack.setCurrentWidget(self.admin_view)
            self.admin_view.refresh()

        add_mode("端末モード", show_terminal).setChecked(True)
        add_mode("ツール別ライブラリ", show_tools)
        add_mode("管理者モード", show_admin)
