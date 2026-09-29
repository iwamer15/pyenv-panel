"""ツール別ライブラリ画面。

  - 左: 登録ツールのカード一覧（状態バッジ付き）。「＋ ツールを追加」/ requirements.txt のドラッグ&ドロップで登録
  - 右上: 選択ツール名と、「このPCでそのまま使えるか」を示すバナー＋「まとめて導入」ボタン
  - 右中央: 全ツールに登場するライブラリの一覧。選択ツールが必要とする行を★・青背景でハイライトし、
           インストール済バージョンが要件より 古い／新しい／一致 かを色と記号で示す。
           各行の「導入／更新／戻す」ボタンでその行だけ即実行できる（右クリックで複数行まとめて操作）
  - 右下: 再スキャン、PyPI取得の切替、進捗バー、折りたたみ式の実行ログ
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import service, tools_registry
from ..config import RuntimePaths
from ..scanner import ScanError
from ..tool_compare import ACTION_STATUSES, LibraryRow, LibStatus, RowEval
from ..tools_registry import ToolsRegistryError
from . import theme

ALL_TOOLS = "__all__"

# 判定ごとの (セル背景, 文字色, 表示ラベル)
STATUS_STYLE: dict[LibStatus, tuple[str, str, str]] = {
    LibStatus.MATCH: (*theme.OK_COLORS, "✔ 一致"),
    LibStatus.SATISFIED: (*theme.OK_COLORS, "✔ OK"),
    LibStatus.UNCONSTRAINED: (*theme.OK_COLORS, "✔ 導入済"),
    LibStatus.MISSING: (*theme.ERROR_COLORS, "✖ 未インストール"),
    LibStatus.OLDER: (*theme.WARN_COLORS, "▼ 古い"),
    LibStatus.NEWER: (*theme.INFO_COLORS, "▲ 新しい"),
    LibStatus.UNKNOWN: (*theme.CAUTION_COLORS, "？ 要確認"),
    LibStatus.CONFLICT: (*theme.CAUTION_COLORS, "⚠ 競合"),
    LibStatus.NOT_APPLICABLE: (*theme.MUTED_COLORS, "対象外"),
    LibStatus.NOT_REQUIRED: ("#ffffff", "#94a3b8", "—"),
}
OK_STATUSES = {LibStatus.MATCH, LibStatus.SATISFIED, LibStatus.UNCONSTRAINED}
NEEDED_ROW_BG = QColor("#eff6ff")   # 選択ツールが必要とする行のハイライト
DIM_FG = QColor("#94a3b8")

COL_STAR, COL_NAME, COL_SPEC, COL_INSTALLED, COL_STATUS, COL_ACTION, COL_USERS = range(7)
COLUMNS = ["", "ライブラリ", "必要なバージョン", "このPCのバージョン", "状態", "操作", "使用ツール"]

FILTER_ALL, FILTER_NEEDED, FILTER_ACTION = range(3)


def row_action(ev: RowEval) -> tuple[str, bool, str] | None:
    """行の「操作」ボタンの (ラベル, upgrade, 説明)。ボタンを出さない行は None。"""
    if not ev.needed or not ev.install_spec:
        return None
    if ev.status == LibStatus.MISSING:
        return "導入", False, f"{ev.install_spec} をインストールします"
    if ev.status == LibStatus.OLDER:
        return "更新", False, f"要件（{ev.specifier}）を満たすバージョンへ更新します"
    if ev.status == LibStatus.NEWER:
        return "戻す", False, f"要件（{ev.specifier}）の範囲へダウングレードします"
    if ev.status == LibStatus.UNKNOWN:
        return "合わせる", False, f"要件（{ev.specifier}）に合わせて入れ直します"
    return "最新へ", True, f"要件（{ev.specifier or '指定なし'}）の範囲内で最新版へ更新します"


class ToolInstallWorker(QThread):
    progress = Signal(str)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, paths: RuntimePaths, target_python: str, specs: list[str], allow_online: bool, upgrade: bool):
        super().__init__()
        self._args = (paths, target_python, specs, allow_online, upgrade)

    def run(self):
        paths, target_python, specs, allow_online, upgrade = self._args
        try:
            results = service.run_tool_install(
                paths, target_python, specs, allow_online=allow_online, upgrade=upgrade,
                progress_cb=self.progress.emit,
            )
            self.finished_ok.emit(results)
        except Exception as e:  # noqa: BLE001 - UIに伝える
            self.failed.emit(str(e))


class RegisterToolDialog(QDialog):
    def __init__(self, parent=None, initial_path: str = ""):
        super().__init__(parent)
        self.setWindowTitle("ツールを追加")
        self.resize(560, 0)
        form = QFormLayout(self)

        intro = QLabel("ツール名と、そのツールが必要とするライブラリを書いた requirements.txt を指定してください。")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        form.addRow(intro)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("requirements.txt のパス")
        browse = QPushButton("参照…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("requirements.txt", path_row)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: 画像学習ツール")
        form.addRow("ツール名", self.name_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("例: 学習データの前処理と学習を行う")
        form.addRow("説明（任意）", self.desc_edit)

        self.copy_check = QCheckBox("共有フォルダにコピーして保存する（全PCで同じ内容を参照。推奨）")
        self.copy_check.setChecked(True)
        form.addRow("", self.copy_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("追加")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if initial_path:
            self._set_path(initial_path)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "requirements.txt を選択", "", "requirements (*.txt);;すべて (*)")
        if path:
            self._set_path(path)

    def _set_path(self, path: str):
        self.path_edit.setText(path)
        if not self.name_edit.text().strip():
            # 多くの場合 requirements.txt はツールのフォルダ直下にあるので、フォルダ名を候補にする
            self.name_edit.setText(Path(path).parent.name)
            self.name_edit.selectAll()
            self.name_edit.setFocus()


class ToolCard(QWidget):
    """左の一覧に並べるツール1件分の表示（名前・説明・状態バッジ）。"""

    def __init__(self, name: str, description: str, badges: list[QLabel], parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        title = QLabel(name)
        title.setStyleSheet("font-weight:bold; font-size:14px; background:transparent;")
        layout.addWidget(title)
        if description:
            # 1行に収めて高さを揃える（全文はツールチップ）
            desc = QLabel()
            desc.setObjectName("muted")
            desc.setStyleSheet("font-size:12px; background:transparent;")
            desc.setText(desc.fontMetrics().elidedText(description, Qt.ElideRight, 220))
            desc.setToolTip(description)
            layout.addWidget(desc)
        badge_row = QHBoxLayout()
        badge_row.setSpacing(4)
        for b in badges:
            badge_row.addWidget(b)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)


class ToolsView(QWidget):
    def __init__(self, paths: RuntimePaths, target_python_getter: Callable[[], str], parent=None):
        super().__init__(parent)
        self.paths = paths
        self._target_python_getter = target_python_getter
        self.result: service.ToolsScanResult | None = None
        self._worker: ToolInstallWorker | None = None
        self._loaded = False
        self._rows_cache: list[tuple[LibraryRow, RowEval]] = []
        self._progress_done = 0
        self._selected: str | None = None   # 選択中のツールID（ALL_TOOLS含む）。None は「既定=先頭のツール」

        self.setAcceptDrops(True)
        self._build_ui()
        QShortcut(QKeySequence("F5"), self, activated=self.rescan)

    # ------------------------------------------------------------------ UI構築
    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(16)

        # ---- 左: ツール一覧
        left = QVBoxLayout()
        left.setSpacing(8)
        title = QLabel("ツール")
        title.setObjectName("h2")
        left.addWidget(title)
        self.add_tool_btn = QPushButton("＋ ツールを追加")
        self.add_tool_btn.setObjectName("primary")
        self.add_tool_btn.clicked.connect(lambda: self.add_tool())
        left.addWidget(self.add_tool_btn)
        self.tool_list = QListWidget()
        self.tool_list.setObjectName("toollist")
        self.tool_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.tool_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tool_list.currentItemChanged.connect(self._on_tool_changed)
        left.addWidget(self.tool_list, 1)
        drop_hint = QLabel("requirements.txt をこの画面へ\nドラッグ&ドロップしても追加できます")
        drop_hint.setObjectName("muted")
        drop_hint.setAlignment(Qt.AlignCenter)
        drop_hint.setStyleSheet("border:1px dashed #cbd5e1; border-radius:8px; padding:10px; font-size:12px;")
        left.addWidget(drop_hint)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(270)
        root.addWidget(left_w)

        # ---- 右: 空状態 / 詳細 を切り替える
        self.right_stack = QStackedWidget()
        root.addWidget(self.right_stack, 1)
        self.right_stack.addWidget(self._build_empty_state())
        self.right_stack.addWidget(self._build_detail())

    def _build_empty_state(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addStretch(1)
        icon = QLabel("🧰")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size:48px;")
        msg = QLabel("まだツールが登録されていません")
        msg.setObjectName("h1")
        msg.setAlignment(Qt.AlignCenter)
        sub = QLabel("ツールの requirements.txt を登録すると、このPCに足りないライブラリや\n"
                     "バージョンの古い・新しいライブラリがひと目でわかり、ボタン1つで導入できます。")
        sub.setObjectName("muted")
        sub.setAlignment(Qt.AlignCenter)
        btn = QPushButton("＋ 最初のツールを追加")
        btn.setObjectName("primary")
        btn.clicked.connect(lambda: self.add_tool())
        for x in (icon, msg, sub):
            layout.addWidget(x)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addStretch(2)
        return w

    def _build_detail(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 見出し: ツール名 + 説明 + ⋯メニュー
        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        self.title_label = QLabel("-")
        self.title_label.setObjectName("h1")
        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("muted")
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        head.addLayout(title_box, 1)
        self.more_btn = QToolButton()
        self.more_btn.setText("ツールの操作 ▾")
        self.more_btn.setStyleSheet(
            "QToolButton { border:1px solid #cbd5e1; border-radius:6px; padding:5px 10px; background:white; }"
            "QToolButton::menu-indicator { image:none; width:0; }"
        )
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        more_menu = QMenu(self.more_btn)
        more_menu.addAction("requirements.txt を開く", self.open_requirements)
        more_menu.addAction("requirements.txt のフォルダを開く", lambda: self.open_requirements(folder=True))
        more_menu.addSeparator()
        more_menu.addAction("このツールの登録を解除…", self.remove_tool)
        self.more_btn.setMenu(more_menu)
        head.addWidget(self.more_btn, 0, Qt.AlignTop)
        layout.addLayout(head)

        # 状態バナー + まとめて導入
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(14, 10, 10, 10)
        self.banner_label = QLabel("")
        self.banner_label.setTextFormat(Qt.RichText)
        self.banner_label.setWordWrap(True)
        banner_layout.addWidget(self.banner_label, 1)
        self.install_all_btn = QPushButton("まとめて導入")
        self.install_all_btn.setObjectName("primary")
        self.install_all_btn.clicked.connect(self.install_all_actions)
        banner_layout.addWidget(self.install_all_btn)
        layout.addWidget(self.banner)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        bg, fg = theme.CAUTION_COLORS
        self.warning_label.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:6px; padding:6px 10px;")
        self.warning_label.setVisible(False)
        layout.addWidget(self.warning_label)

        # 絞り込み（セグメント）+ 検索
        filter_row = QHBoxLayout()
        filter_row.setSpacing(0)
        self.filter_group = QButtonGroup(self)
        self.filter_buttons: list[QPushButton] = []
        for fid, label in ((FILTER_ALL, "すべて"), (FILTER_NEEDED, "このツールで必要"), (FILTER_ACTION, "要対応のみ")):
            b = QPushButton(label)
            b.setObjectName("segment")
            b.setCheckable(True)
            self.filter_group.addButton(b, fid)
            self.filter_buttons.append(b)
            filter_row.addWidget(b)
        self.filter_buttons[FILTER_ALL].setChecked(True)
        self.filter_group.idClicked.connect(lambda _: self._refresh_table())
        filter_row.addStretch(1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 ライブラリ名で絞り込み")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedWidth(240)
        self.search_edit.textChanged.connect(self._refresh_table)
        filter_row.addWidget(self.search_edit)
        layout.addLayout(filter_row)

        # 一覧
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_USERS, QHeaderView.Stretch)
        header.setHighlightSections(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.table, 1)

        legend = QLabel(
            "★ 青背景 = 必要なライブラリ　▼古い / ▲新しい = 要件と比べたこのPCのバージョン　"
            "右クリックで複数行をまとめて操作"
        )
        legend.setObjectName("muted")
        legend.setStyleSheet("font-size:12px;")
        legend.setWordWrap(True)
        layout.addWidget(legend)

        # 下部: 再スキャン / PyPI切替 / 進捗 / ログ
        bottom = QHBoxLayout()
        self.rescan_btn = QPushButton("⟳ 再スキャン")
        self.rescan_btn.setToolTip("このPCのライブラリと requirements.txt を読み直します（F5）")
        self.rescan_btn.clicked.connect(self.rescan)
        bottom.addWidget(self.rescan_btn)
        self.online_check = QCheckBox("PyPI（インターネット）からも取得")
        self.online_check.setToolTip(
            "OFF: 共有フォルダの承認済み .whl だけから導入します（オフライン）\n"
            "ON : 共有フォルダの .whl を優先し、無いものはPyPIから取得します"
        )
        bottom.addWidget(self.online_check)
        bottom.addStretch(1)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        bottom.addWidget(self.progress_label)
        bottom.addWidget(self.progress)
        self.log_toggle = QPushButton("ログを表示 ▾")
        self.log_toggle.setObjectName("link")
        self.log_toggle.clicked.connect(lambda: self._set_log_visible(not self.log.isVisible()))
        bottom.addWidget(self.log_toggle)
        layout.addLayout(bottom)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setFixedHeight(130)
        self.log.setVisible(False)
        layout.addWidget(self.log)
        return w

    def _set_log_visible(self, visible: bool):
        self.log.setVisible(visible)
        self.log_toggle.setText("ログを隠す ▴" if visible else "ログを表示 ▾")

    def _append_log(self, text: str):
        self.log.appendPlainText(text)

    # ------------------------------------------------------------------ ドラッグ&ドロップ登録
    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile() and urls[0].toLocalFile().lower().endswith(".txt"):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_tool(event.mimeData().urls()[0].toLocalFile())

    # ------------------------------------------------------------------ スキャン
    def set_paths(self, paths: RuntimePaths):
        """共有フォルダを切り替えたとき（環境バーから）に呼ばれる。"""
        self.paths = paths
        self._loaded = False

    def ensure_loaded(self):
        """画面を初めて開いたときだけスキャンする（起動を遅くしないため）。"""
        if not self._loaded:
            self.rescan()

    def rescan(self):
        target_python = self._target_python_getter()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.result = service.run_tools_scan(self.paths, target_python)
        except (ScanError, ToolsRegistryError) as e:
            self._append_log(f"[エラー] {e}")
            self._set_log_visible(True)
            QMessageBox.warning(self, "スキャン失敗", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._loaded = True
        self.online_check.setChecked(self.result.registry.allow_online)
        self._populate_tool_list()
        self._refresh_detail()
        table = self.result.table
        self._append_log(f"スキャン完了: 登録ツール {len(table.tool_names)} 件 / ライブラリ {len(table.rows)} 件")

    def _tool_badges(self, tool_id: str | None) -> list[QLabel]:
        table = self.result.table
        if tool_id in table.tool_errors:
            return [theme.pill("読込エラー", theme.ERROR_COLORS)]
        counts = table.summary(tool_id)
        badges = []
        if counts.get(LibStatus.MISSING):
            badges.append(theme.pill(f"未インストール {counts[LibStatus.MISSING]}", theme.ERROR_COLORS))
        if counts.get(LibStatus.OLDER):
            badges.append(theme.pill(f"古い {counts[LibStatus.OLDER]}", theme.WARN_COLORS))
        if counts.get(LibStatus.NEWER):
            badges.append(theme.pill(f"新しい {counts[LibStatus.NEWER]}", theme.INFO_COLORS))
        if counts.get(LibStatus.UNKNOWN):
            badges.append(theme.pill(f"要確認 {counts[LibStatus.UNKNOWN]}", theme.CAUTION_COLORS))
        if counts.get(LibStatus.CONFLICT):
            badges.append(theme.pill(f"競合 {counts[LibStatus.CONFLICT]}", theme.CAUTION_COLORS))
        if not badges:
            badges.append(theme.pill("✔ 使えます", theme.OK_COLORS))
        return badges

    def _populate_tool_list(self):
        table = self.result.table
        self.tool_list.blockSignals(True)
        self.tool_list.clear()
        tools = [(t.id, t.name, t.description) for t in self.result.registry.tools]
        entries = ([(ALL_TOOLS, "すべてのツール", "登録済みツール全体をまとめて確認")] + tools) if tools else []
        select_row = 1 if len(entries) > 1 else 0   # 既定は最初のツールを開く
        for i, (tid, name, desc) in enumerate(entries):
            key = None if tid == ALL_TOOLS else tid
            card = ToolCard(name, desc, self._tool_badges(key))
            item = QListWidgetItem()
            item.setData(Qt.UserRole, tid)
            card.ensurePolished()
            item.setSizeHint(card.sizeHint() + QSize(0, 6))
            self.tool_list.addItem(item)
            self.tool_list.setItemWidget(item, card)
            if tid == self._selected:
                select_row = i
        if entries:
            self.tool_list.setCurrentRow(select_row)
            self._selected = entries[select_row][0]
        else:
            self._selected = None
        self.tool_list.blockSignals(False)
        self.right_stack.setCurrentIndex(1 if self.result.registry.tools else 0)

    def _on_tool_changed(self, current, _previous=None):
        if current is not None:
            self._selected = current.data(Qt.UserRole)
            self._refresh_detail()

    def _current_tool_id(self) -> str | None:
        """表示中のツールID。「すべてのツール」は None。"""
        return None if self._selected in (None, ALL_TOOLS) else self._selected

    # ------------------------------------------------------------------ 表示
    def _refresh_detail(self):
        if self.result is None:
            return
        tool_id = self._current_tool_id()
        table = self.result.table
        tool = self.result.registry.find(tool_id) if tool_id else None
        self.title_label.setText(tool.name if tool else "すべてのツール")
        self.subtitle_label.setText(
            (tool.description or tool.requirements) if tool else "全ツールの要件を同時に満たせるかを確認します"
        )
        self.more_btn.setVisible(tool is not None)
        is_all = tool_id is None
        self.filter_buttons[FILTER_NEEDED].setText("いずれかのツールで必要" if is_all else "このツールで必要")
        self._refresh_banner(tool_id)
        self._refresh_warnings(tool_id)
        self._refresh_table()

    def _refresh_banner(self, tool_id: str | None):
        table = self.result.table
        name = table.tool_names.get(tool_id, "") if tool_id else "すべてのツール"
        counts = table.summary(tool_id)
        actions = table.action_specs(tool_id)
        conflicts = counts.get(LibStatus.CONFLICT, 0)
        total = sum(counts.values())

        if tool_id in table.tool_errors:
            colors, icon, text = theme.ERROR_COLORS, "✖", f"requirements.txt を読み込めません。<br>{table.tool_errors[tool_id]}"
        elif actions:
            parts = []
            for status, label in ((LibStatus.MISSING, "未インストール"), (LibStatus.OLDER, "古い"),
                                  (LibStatus.NEWER, "新しい"), (LibStatus.UNKNOWN, "要確認")):
                if counts.get(status):
                    parts.append(f"{label} {counts[status]}")
            colors, icon = theme.WARN_COLORS, "!"
            text = f"<b>あと {len(actions)} 件の対応で {name} が使えます</b><br>{' ／ '.join(parts)}"
            if conflicts:
                text += f"<br>⚠ 競合 {conflicts} 件はツールを選んで個別に導入してください"
        elif conflicts:
            colors, icon = theme.CAUTION_COLORS, "⚠"
            text = (f"<b>ツール同士でバージョン指定が両立しないライブラリが {conflicts} 件あります</b><br>"
                    "左の一覧でツールを選び、使うツールに合わせて導入してください")
        else:
            colors, icon = theme.OK_COLORS, "✔"
            text = f"<b>{name} はこのPCでそのまま使えます</b><br>必要なライブラリ {total} 件がすべて要件を満たしています"

        bg, fg = colors
        self.banner.setStyleSheet(f"QFrame#banner {{ background:{bg}; }} QLabel {{ color:{fg}; background:transparent; }}")
        self.banner_label.setText(f"<span style='font-size:20px'>{icon}</span>&nbsp;&nbsp;{text}")
        self.install_all_btn.setVisible(bool(actions) and tool_id not in table.tool_errors)
        self.install_all_btn.setText(f"まとめて導入（{len(actions)}件）")

    def _refresh_warnings(self, tool_id: str | None):
        table = self.result.table
        notes = []
        for tid in ([tool_id] if tool_id else list(table.tool_warnings)):
            notes += [f"{table.tool_names[tid]}: {w}" for w in table.tool_warnings.get(tid, [])]
        if tool_id is None:
            notes += [f"{table.tool_names[t]}: {e}" for t, e in table.tool_errors.items()]
        self.warning_label.setText("⚠ " + "\n⚠ ".join(notes) if notes else "")
        self.warning_label.setVisible(bool(notes))

    def _visible_rows(self) -> list[tuple[LibraryRow, RowEval]]:
        tool_id = self._current_tool_id()
        mode = self.filter_group.checkedId()
        query = self.search_edit.text().strip().lower()
        out = []
        for row in self.result.table.rows:
            ev = row.evaluate(tool_id)
            if mode == FILTER_NEEDED and not ev.needed:
                continue
            if mode == FILTER_ACTION and not (ev.needed and (ev.status in ACTION_STATUSES or ev.status == LibStatus.CONFLICT)):
                continue
            if query and query not in row.name.lower() and query not in row.key:
                continue
            out.append((row, ev))
        # 必要な行を上に、その中で要対応を先頭に並べる
        out.sort(key=lambda re_: (not re_[1].needed, re_[1].status not in ACTION_STATUSES, re_[0].key))
        return out

    def _refresh_table(self):
        if self.result is None:
            return
        table = self.result.table
        rows = self._visible_rows()
        self._rows_cache = rows
        self.table.clearContents()
        self.table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        for r, (row, ev) in enumerate(rows):
            bg, fg, status_label = STATUS_STYLE[ev.status]
            users = [table.tool_names[t] for t in row.reqs] + [f"{table.tool_names[t]}(対象外)" for t in row.excluded]
            values = {
                COL_STAR: "★" if ev.needed else "",
                COL_NAME: row.name,
                COL_SPEC: ev.specifier or ("指定なし" if ev.needed else ""),
                COL_INSTALLED: row.installed_version or "—",
                COL_STATUS: status_label,
                COL_ACTION: "",
                COL_USERS: ("⚠ " if row.conflicts else "") + ", ".join(users),
            }
            tooltip = self._row_tooltip(row)
            for c, value in values.items():
                cell = QTableWidgetItem(value)
                cell.setToolTip(tooltip)
                if ev.needed:
                    cell.setBackground(QBrush(NEEDED_ROW_BG))
                    if c in (COL_STAR, COL_NAME):
                        cell.setFont(bold)
                else:
                    cell.setForeground(QBrush(DIM_FG))
                if c == COL_STAR:
                    cell.setTextAlignment(Qt.AlignCenter)
                    cell.setForeground(QBrush(QColor("#d97706")))
                elif c == COL_STATUS:
                    cell.setBackground(QBrush(QColor(bg)))
                    cell.setForeground(QBrush(QColor(fg)))
                    cell.setFont(bold)
                    cell.setTextAlignment(Qt.AlignCenter)
                elif c == COL_USERS and row.conflicts:
                    cell.setForeground(QBrush(QColor(theme.CAUTION_COLORS[1])))
                self.table.setItem(r, c, cell)
            self._set_action_widget(r, row, ev)

    def _set_action_widget(self, r: int, row: LibraryRow, ev: RowEval):
        action = row_action(ev)
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(6, 2, 6, 2)
        if action is None:
            if ev.status == LibStatus.CONFLICT:
                note = QLabel("個別に導入")
                note.setToolTip("ツール同士の要件が両立しないため、左の一覧で使うツールを選んで導入してください")
                note.setObjectName("muted")
                note.setStyleSheet("font-size:11px;")
                lay.addWidget(note)
        else:
            label, upgrade, tip = action
            btn = QPushButton(label)
            btn.setToolTip(tip)
            btn.setCursor(Qt.PointingHandCursor)
            if ev.status in OK_STATUSES:
                btn.setObjectName("link")        # 既に要件OKの行は控えめに
            else:
                btn.setObjectName("rowaction")
                bg, fg = STATUS_STYLE[ev.status][:2]
                btn.setStyleSheet(f"QPushButton {{ border-color:{fg}; color:{fg}; font-weight:bold; }}")
            btn.clicked.connect(lambda _=False, s=ev.install_spec, u=upgrade, st=ev.status, n=row.name:
                                self._run_single(n, s, u, st))
            lay.addWidget(btn)
        lay.addStretch(1)
        self.table.setCellWidget(r, COL_ACTION, holder)

    def _row_tooltip(self, row: LibraryRow) -> str:
        names = self.result.table.tool_names
        lines = [f"{row.name}（このPC: {row.installed_version or '未インストール'}）"]
        for tid, req in row.reqs.items():
            lines.append(f"  {names[tid]}: {req.specifier or '指定なし'}  [{req.source}]")
        for tid, req in row.excluded.items():
            lines.append(f"  {names[tid]}: 環境マーカーによりこのPCでは対象外（{req.marker}）")
        if row.conflicts:
            lines.append("⚠ 競合:")
            lines += [f"  {m}" for m in row.conflicts]
        return "\n".join(lines)

    # ------------------------------------------------------------------ 右クリックメニュー
    def _selected_rows(self) -> list[tuple[LibraryRow, RowEval]]:
        idx = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._rows_cache[i] for i in idx if i < len(self._rows_cache)]

    def _show_context_menu(self, pos):
        clicked = self.table.indexAt(pos)
        if clicked.isValid() and not self.table.selectionModel().isRowSelected(clicked.row(), clicked.parent()):
            self.table.selectRow(clicked.row())
        selected = self._selected_rows()
        if not selected:
            return
        menu = QMenu(self)
        n = len(selected)
        menu.addAction(f"要件どおり導入（{n}件）", lambda: self.install_rows(selected, upgrade=False))
        menu.addAction(f"要件の範囲内で最新へ更新（{n}件）", lambda: self.install_rows(selected, upgrade=True))
        menu.addSeparator()
        names = [row.name for row, _ in selected]
        menu.addAction("ライブラリ名をコピー", lambda: QGuiApplication.clipboard().setText("\n".join(names)))
        if n == 1:
            menu.addAction("PyPIのページを開く",
                           lambda: QDesktopServices.openUrl(QUrl(f"https://pypi.org/project/{selected[0][0].key}/")))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ 導入・更新
    def _spec_for(self, row: LibraryRow, ev: RowEval) -> str | None:
        if ev.install_spec:
            return ev.install_spec
        # 表示中のツールでは不要な行を選んだ場合は、全ツール合算の要件で導入する
        return row.evaluate(None).install_spec

    def _run_single(self, name: str, spec: str, upgrade: bool, status: LibStatus):
        """行ボタン: ダウングレードだけ確認し、それ以外は即実行する。"""
        if status == LibStatus.NEWER and QMessageBox.question(
            self, "ダウングレードの確認",
            f"{name} はこのツールの要件より新しいバージョンが入っています。\n"
            f"{spec} の範囲へ戻します。ほかのツールが新しいバージョンを必要としていないか確認してください。\n\n実行しますか？",
        ) != QMessageBox.Yes:
            return
        self._start_install([spec], upgrade, confirm=False)

    def install_rows(self, rows: list[tuple[LibraryRow, RowEval]], upgrade: bool):
        specs, skipped = [], []
        for row, ev in rows:
            spec = self._spec_for(row, ev)
            (specs.append(spec) if spec else skipped.append(row.name))
        if skipped:
            self._append_log(f"[スキップ] 要件が競合／対象外のため導入できません: {', '.join(skipped)}")
        self._start_install(specs, upgrade)

    def install_all_actions(self):
        if self.result is None:
            return
        actions = self.result.table.action_specs(self._current_tool_id())
        self._start_install([ev.install_spec for _, ev in actions], upgrade=False)

    def _start_install(self, specs: list[str], upgrade: bool, confirm: bool = True):
        if not specs:
            QMessageBox.information(self, "対象なし", "導入・更新が必要なライブラリはありません。")
            return
        source = "共有フォルダ＋PyPI" if self.online_check.isChecked() else "共有フォルダの .whl のみ（オフライン）"
        if confirm:
            downgrades = [row.name for row, ev in self._rows_cache
                          if ev.status == LibStatus.NEWER and ev.install_spec in specs]
            msg = (
                f"次の {len(specs)} 件を{'要件の範囲内で最新へ更新' if upgrade else '要件どおりに導入'}します。\n\n"
                + "\n".join(f"  ・{s}" for s in specs)
                + f"\n\n取得元: {source}"
            )
            if downgrades:
                msg += f"\n\n※ 要件より新しいため、要件のバージョンへ戻します（ダウングレード）: {', '.join(downgrades)}"
            if QMessageBox.question(self, "導入の確認", msg) != QMessageBox.Yes:
                return

        self._set_busy(True, len(specs))
        self._append_log(f"{'更新' if upgrade else '導入'}を開始します（{source}）…")
        self._worker = ToolInstallWorker(
            self.paths, self._target_python_getter(), specs, self.online_check.isChecked(), upgrade,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_install_finished)
        self._worker.failed.connect(self._on_install_failed)
        self._worker.start()

    def _on_progress(self, text: str):
        self._append_log(text)
        self._progress_done += 1
        self.progress.setValue(self._progress_done - 1)
        self.progress_label.setText(f"{text}（{self._progress_done}/{self.progress.maximum()}）")

    def _on_install_finished(self, results):
        ng = [r for r in results if not r.success]
        for r in results:
            self._append_log(f"  [{'OK' if r.success else 'NG'}] {r.name}: {r.message}")
        self._set_busy(False)
        self.rescan()
        if ng:
            self._set_log_visible(True)
            hint = "" if self.online_check.isChecked() else \
                "\n\n共有フォルダに該当の .whl が無い場合は「PyPI（インターネット）からも取得」をONにして再実行してください。"
            QMessageBox.warning(self, "一部失敗", f"{len(ng)} 件の導入に失敗しました（詳細は下のログ）。{hint}")
        else:
            self.progress_label.setText(f"✔ {len(results)} 件完了")

    def _on_install_failed(self, message: str):
        self._set_busy(False)
        self._append_log(f"[エラー] 導入に失敗しました: {message}")
        self._set_log_visible(True)
        QMessageBox.warning(self, "導入失敗", message)

    def _set_busy(self, busy: bool, total: int = 0):
        for w in (self.rescan_btn, self.install_all_btn, self.add_tool_btn, self.more_btn, self.tool_list, self.table):
            w.setEnabled(not busy)
        self.progress.setVisible(busy)
        if busy:
            self._progress_done = 0
            self.progress.setRange(0, total)
            self.progress.setValue(0)
            self.progress_label.setText("準備中…")
            QApplication.setOverrideCursor(Qt.BusyCursor)
        else:
            self.progress_label.setText("")
            QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------------ ツール登録
    def add_tool(self, initial_path: str = ""):
        dlg = RegisterToolDialog(self, initial_path=initial_path)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            entry = tools_registry.register_tool(
                self.paths, dlg.name_edit.text(), Path(dlg.path_edit.text().strip()),
                description=dlg.desc_edit.text(), copy_to_runtime=dlg.copy_check.isChecked(),
            )
        except ToolsRegistryError as e:
            QMessageBox.warning(self, "追加できませんでした", str(e))
            return
        self._append_log(f"ツールを追加しました: {entry.name}（{entry.requirements}）")
        self._selected = entry.id
        self.rescan()

    def remove_tool(self):
        tool_id = self._current_tool_id()
        if tool_id is None:
            return
        name = self.result.table.tool_names.get(tool_id, tool_id)
        if QMessageBox.question(
            self, "登録解除の確認",
            f"「{name}」を一覧から外します（requirements.txt 自体は削除しません）。よろしいですか？",
        ) != QMessageBox.Yes:
            return
        try:
            tools_registry.unregister_tool(self.paths, tool_id)
        except ToolsRegistryError as e:
            QMessageBox.warning(self, "登録解除できませんでした", str(e))
            return
        self._append_log(f"登録を解除しました: {name}")
        self._selected = None
        self.rescan()

    def open_requirements(self, folder: bool = False):
        tool_id = self._current_tool_id()
        tool = self.result.registry.find(tool_id) if (self.result and tool_id) else None
        if tool is None:
            return
        path = tools_registry.resolve_requirements_path(self.paths, tool)
        if not path.exists():
            QMessageBox.warning(self, "ファイルがありません", f"見つかりません: {path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if folder else path)))
