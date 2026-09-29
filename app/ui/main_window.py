"""メインウィンドウ。

  - 左: サイドバーで画面を切り替える（ツール別ライブラリ / このPCの標準構成（端末モード） / 管理者）
  - 上: 全画面共通の「環境バー」。対象Pythonと共有フォルダを表示し、その場で変更できる
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..config import RuntimePaths, is_env_overridden, write_user_config
from ..scanner import ScanError, get_local_python_version
from . import theme
from .admin_view import AdminView
from .terminal_view import TerminalView
from .tools_view import ToolsView

PAGE_TOOLS, PAGE_TERMINAL, PAGE_ADMIN = range(3)
NAV_ITEMS = [
    ("🧰  ツール別ライブラリ", "登録ツールの requirements.txt と、このPCのライブラリを比べて導入・更新する"),
    ("🖥  このPCの標準構成", "組織標準（マニフェスト）のPython・ライブラリと比べて同期する（端末モード）"),
    ("📊  管理者", "全端末の準拠状況の集計と、マニフェストの編集"),
]


class EnvBar(QFrame):
    """対象Python・共有フォルダの表示と変更。"""

    def __init__(self, window: "MainWindow"):
        super().__init__()
        self.setObjectName("envbar")
        self._window = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(6)

        self.python_value = QLabel("-")
        self.python_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.root_value = QLabel("-")
        self.root_value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        for caption, value, handler, tip in (
            ("対象Python", self.python_value, window.change_target_python,
             "ライブラリを確認・導入する先のPython（python.exe）を選び直します"),
            ("共有フォルダ", self.root_value, window.change_runtime_root,
             "ツール登録・マニフェスト・.whl を置いた共有フォルダ（runtime）を選び直します"),
        ):
            cap = QLabel(caption)
            cap.setObjectName("muted")
            btn = QPushButton("変更…")
            btn.setObjectName("link")
            btn.setToolTip(tip)
            btn.clicked.connect(handler)
            layout.addWidget(cap)
            layout.addWidget(value)
            layout.addWidget(btn)
            layout.addSpacing(18)
        layout.addStretch(1)

    def refresh(self, target_python: str, paths: RuntimePaths, sample: bool):
        try:
            version = get_local_python_version(target_python)
            self.python_value.setText(f"<b>Python {version}</b>  <span style='color:#64748b'>{theme.elide_middle(target_python, 48)}</span>")
        except ScanError:
            self.python_value.setText(f"<b style='color:#991b1b'>実行できません</b>  {theme.elide_middle(target_python, 48)}")
        self.python_value.setToolTip(target_python)
        suffix = "  <span style='color:#9a3412'>（サンプル）</span>" if sample else ""
        self.root_value.setText(theme.elide_middle(str(paths.root), 48) + suffix)
        self.root_value.setToolTip(str(paths.root))


class MainWindow(QMainWindow):
    def __init__(self, paths: RuntimePaths, target_python: str, group: str = "default"):
        super().__init__()
        self.setWindowTitle("PyEnvPanel — Python環境統一管理ツール")
        self.resize(1240, 760)
        self.paths = paths
        self.group = group

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.env_bar = EnvBar(self)
        right.addWidget(self.env_bar)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        outer.addLayout(right, 1)
        self.setCentralWidget(central)

        self._build_views(target_python)
        self.nav.setCurrentRow(PAGE_TOOLS)

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setFixedWidth(210)
        side.setStyleSheet("background:#0f172a;")
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 16, 0, 12)
        title = QLabel("PyEnvPanel")
        title.setStyleSheet("color:white; font-size:18px; font-weight:bold; padding:0 18px;")
        sub = QLabel("Python環境統一管理ツール")
        sub.setStyleSheet("color:#94a3b8; font-size:11px; padding:0 18px 10px 18px;")
        layout.addWidget(title)
        layout.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        for label, tip in NAV_ITEMS:
            item = QListWidgetItem(label)
            item.setToolTip(tip)
            self.nav.addItem(item)
        self.nav.currentRowChanged.connect(self._show_page)
        layout.addWidget(self.nav, 1)
        return side

    def _build_views(self, target_python: str):
        """共有フォルダを切り替えたときも、ここで各画面を作り直す。"""
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.terminal_view = TerminalView(self.paths, target_python, group=self.group)
        # 端末モードでPython本体を入れ直すと対象Pythonが切り替わるため、常に最新値を参照する
        self.tools_view = ToolsView(self.paths, lambda: self.terminal_view.target_python)
        self.admin_view = AdminView(self.paths)
        for w in (self.tools_view, self.terminal_view, self.admin_view):
            self.stack.addWidget(w)
        self._refresh_env_bar()

    @property
    def target_python(self) -> str:
        return self.terminal_view.target_python

    def _is_sample_root(self) -> bool:
        return self.paths.root.name == "sample_runtime"

    def _refresh_env_bar(self):
        self.env_bar.refresh(self.target_python, self.paths, self._is_sample_root())

    def _show_page(self, index: int):
        if index < 0:
            return
        self.stack.setCurrentIndex(index)
        self._refresh_env_bar()   # 端末モードでPythonを入れ直した場合などに追従する
        if index == PAGE_TOOLS:
            self.tools_view.ensure_loaded()
        elif index == PAGE_ADMIN:
            self.admin_view.refresh()

    # ------------------------------------------------------------------ 環境の変更
    def change_target_python(self):
        pattern = "python.exe (python.exe);;すべて (*)" if sys.platform == "win32" else "python (python python3*);;すべて (*)"
        start = str(Path(self.target_python).parent)
        path, _ = QFileDialog.getOpenFileName(self, "対象にするPythonを選択", start, pattern)
        if not path:
            return
        try:
            version = get_local_python_version(path)
        except ScanError as e:
            QMessageBox.warning(self, "Pythonとして実行できません", str(e))
            return
        write_user_config(target_python=path)
        note = ""
        if is_env_overridden("target"):
            note = "\n\n※ 環境変数 PYENV_PANEL_TARGET_PYTHON が設定されているため、次回起動時はそちらが優先されます。"
        self.terminal_view.target_python = path
        self.terminal_view.rescan()
        self.tools_view.set_paths(self.paths)
        if self.stack.currentIndex() == PAGE_TOOLS:
            self.tools_view.ensure_loaded()
        self._refresh_env_bar()
        QMessageBox.information(self, "対象Pythonを変更しました", f"Python {version}\n{path}{note}")

    def change_runtime_root(self):
        path = QFileDialog.getExistingDirectory(self, "共有フォルダ（runtime）を選択", str(self.paths.root))
        if not path:
            return
        new_root = Path(path)
        if not (new_root / "config").is_dir() and QMessageBox.question(
            self, "確認",
            f"{new_root} に config フォルダがありません。\n"
            "新しい共有フォルダとして使いますか？（ツールを追加すると config/tools.json が作られます）",
        ) != QMessageBox.Yes:
            return
        write_user_config(root=str(new_root))
        if is_env_overridden("runtime"):
            QMessageBox.information(
                self, "お知らせ",
                "環境変数 PYENV_PANEL_RUNTIME_ROOT が設定されているため、次回起動時はそちらが優先されます。",
            )
        self.paths = RuntimePaths(new_root)
        current = self.nav.currentRow()
        self._build_views(self.target_python)
        self._show_page(current)
