"""端末モード / 管理者モードを同一ウィンドウ内で切り替えるメインウィンドウ。"""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QStackedWidget, QToolBar

from ..config import RuntimePaths
from .admin_view import AdminView
from .terminal_view import TerminalView


class MainWindow(QMainWindow):
    def __init__(self, paths: RuntimePaths, target_python: str, group: str = "default"):
        super().__init__()
        self.setWindowTitle("Python環境統一管理ツール（プロトタイプ）")
        self.resize(900, 600)

        self.terminal_view = TerminalView(paths, target_python, group=group)
        self.admin_view = AdminView(paths)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.terminal_view)
        self.stack.addWidget(self.admin_view)
        self.setCentralWidget(self.stack)

        self._build_toolbar()
        self.statusBar().showMessage(f"共有ランタイム: {paths.root}")

    def _build_toolbar(self):
        toolbar = QToolBar("モード切替")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        terminal_action = toolbar.addAction("端末モード")
        admin_action = toolbar.addAction("管理者モード")
        terminal_action.setCheckable(True)
        admin_action.setCheckable(True)
        terminal_action.setChecked(True)

        def show_terminal():
            self.stack.setCurrentWidget(self.terminal_view)
            terminal_action.setChecked(True)
            admin_action.setChecked(False)

        def show_admin():
            self.stack.setCurrentWidget(self.admin_view)
            self.admin_view.refresh()
            terminal_action.setChecked(False)
            admin_action.setChecked(True)

        terminal_action.triggered.connect(show_terminal)
        admin_action.triggered.connect(show_admin)
