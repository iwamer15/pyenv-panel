"""ツール別ライブラリ画面。

  - 左: 登録ツール一覧（先頭は「全ツール合算」）。ツールの追加・登録解除・requirements.txt を開く
  - 右上: 対象Python / 判定サマリ / 表示フィルタ
  - 右中央: 全ツールに登場するライブラリの一覧。選択中のツールが必要とする行をハイライトし、
           インストール済バージョンが要件より古い／新しい／一致 かを色と記号で示す
  - 右下: 選択行のインストール・更新、ツール単位のまとめて導入、実行ログ
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import service, tools_registry
from ..config import RuntimePaths
from ..scanner import ScanError
from ..tool_compare import ACTION_STATUSES, LibraryRow, LibStatus, RowEval
from ..tools_registry import ToolsRegistryError

ALL_TOOLS = "__all__"

# 判定ごとの (セル背景, 文字色, 表示ラベル)
STATUS_STYLE: dict[LibStatus, tuple[str, str, str]] = {
    LibStatus.MATCH: ("#dff6dd", "#0b6a0b", "✔ 一致"),
    LibStatus.SATISFIED: ("#dff6dd", "#0b6a0b", "✔ 条件内"),
    LibStatus.UNCONSTRAINED: ("#dff6dd", "#0b6a0b", "✔ 導入済"),
    LibStatus.MISSING: ("#fde7e9", "#a80000", "✖ 未インストール"),
    LibStatus.OLDER: ("#ffe8cc", "#8a4b00", "▼ 古い"),
    LibStatus.NEWER: ("#e0ecff", "#1a4e9c", "▲ 新しい"),
    LibStatus.UNKNOWN: ("#fff4ce", "#795d00", "？ 要確認"),
    LibStatus.CONFLICT: ("#fff4ce", "#795d00", "⚠ 競合"),
    LibStatus.NOT_APPLICABLE: ("#f3f3f3", "#8a8a8a", "対象外"),
    LibStatus.NOT_REQUIRED: ("#ffffff", "#a0a0a0", "-"),
}
NEEDED_ROW_BG = QColor("#eef5fd")   # 選択ツールが必要とする行のハイライト
DIM_FG = QColor("#a0a0a0")

SUMMARY_ORDER = [
    LibStatus.MISSING, LibStatus.OLDER, LibStatus.NEWER, LibStatus.CONFLICT, LibStatus.UNKNOWN,
]
OK_STATUSES = {LibStatus.MATCH, LibStatus.SATISFIED, LibStatus.UNCONSTRAINED}

COLUMNS = ["", "ライブラリ", "要件（登録バージョン）", "インストール済", "判定", "使用ツール"]


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ツールを登録")
        self.resize(520, 0)
        form = QFormLayout(self)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例: 画像学習ツール")
        form.addRow("ツール名", self.name_edit)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("requirements.txt のパス")
        browse = QPushButton("参照…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("requirements.txt", path_row)

        self.desc_edit = QLineEdit()
        form.addRow("説明（任意）", self.desc_edit)

        self.copy_check = QCheckBox("共有ランタイムにコピーして保存する（全端末で同じ内容を参照。推奨）")
        self.copy_check.setChecked(True)
        form.addRow("", self.copy_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "requirements.txt を選択", "", "requirements (*.txt);;すべて (*)")
        if path:
            self.path_edit.setText(path)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(path).parent.name)


class ToolsView(QWidget):
    def __init__(self, paths: RuntimePaths, target_python_getter: Callable[[], str], parent=None):
        super().__init__(parent)
        self.paths = paths
        self._target_python_getter = target_python_getter
        self.result: service.ToolsScanResult | None = None
        self._worker: ToolInstallWorker | None = None
        self._loaded = False
        self._rows_cache: list[tuple[LibraryRow, RowEval]] = []

        self._build_ui()

    # ------------------------------------------------------------------ UI構築
    def _build_ui(self):
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # 左: ツール一覧
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("登録ツール"))
        self.tool_list = QListWidget()
        self.tool_list.currentItemChanged.connect(lambda *_: self._refresh_table())
        left_layout.addWidget(self.tool_list, 1)
        tool_btns = QHBoxLayout()
        self.add_tool_btn = QPushButton("追加…")
        self.remove_tool_btn = QPushButton("登録解除")
        self.open_req_btn = QPushButton("requirements.txtを開く")
        self.add_tool_btn.clicked.connect(self.add_tool)
        self.remove_tool_btn.clicked.connect(self.remove_tool)
        self.open_req_btn.clicked.connect(self.open_requirements)
        tool_btns.addWidget(self.add_tool_btn)
        tool_btns.addWidget(self.remove_tool_btn)
        left_layout.addLayout(tool_btns)
        left_layout.addWidget(self.open_req_btn)
        splitter.addWidget(left)

        # 右: ライブラリ一覧
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.python_label = QLabel("対象Python: -")
        right_layout.addWidget(self.python_label)

        self.summary_label = QLabel("")
        self.summary_label.setTextFormat(Qt.RichText)
        right_layout.addWidget(self.summary_label)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color:#795d00;")
        self.warning_label.setVisible(False)
        right_layout.addWidget(self.warning_label)

        filter_row = QHBoxLayout()
        self.only_needed_check = QCheckBox("選択ツールで必要なライブラリのみ表示")
        self.only_action_check = QCheckBox("要対応のみ表示")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("ライブラリ名で絞り込み")
        for w in (self.only_needed_check, self.only_action_check):
            w.toggled.connect(self._refresh_table)
            filter_row.addWidget(w)
        self.search_edit.textChanged.connect(self._refresh_table)
        filter_row.addStretch(1)
        filter_row.addWidget(self.search_edit)
        right_layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(lambda idx: self.install_selected(upgrade=False, rows=[idx.row()]))
        right_layout.addWidget(self.table, 1)

        legend = QLabel(
            "★ = 選択ツールが必要とするライブラリ（青背景）　"
            "▼古い: 要件より古い／▲新しい: 要件より新しい（導入すると要件のバージョンに戻します）　"
            "行をダブルクリックでその行だけ導入"
        )
        legend.setStyleSheet("color:#555;")
        legend.setWordWrap(True)
        right_layout.addWidget(legend)

        btn_row = QHBoxLayout()
        self.rescan_btn = QPushButton("再スキャン")
        self.install_sel_btn = QPushButton("選択行を要件どおり導入")
        self.upgrade_sel_btn = QPushButton("選択行を最新へ更新（要件の範囲内）")
        self.install_all_btn = QPushButton("要対応をまとめて導入")
        self.online_check = QCheckBox("PyPI（インターネット）からも取得")
        self.online_check.setToolTip(
            "OFF: 共有ホイールハウス（社内承認済みの .whl）のみから導入（--no-index）\n"
            "ON : 共有ホイールハウスを優先しつつ、無いものはPyPIから取得"
        )
        self.rescan_btn.clicked.connect(self.rescan)
        self.install_sel_btn.clicked.connect(lambda: self.install_selected(upgrade=False))
        self.upgrade_sel_btn.clicked.connect(lambda: self.install_selected(upgrade=True))
        self.install_all_btn.clicked.connect(self.install_all_actions)
        for w in (self.rescan_btn, self.install_sel_btn, self.upgrade_sel_btn, self.install_all_btn):
            btn_row.addWidget(w)
        btn_row.addStretch(1)
        btn_row.addWidget(self.online_check)
        right_layout.addLayout(btn_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setFixedHeight(110)
        right_layout.addWidget(self.log)

        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        left.setMinimumWidth(270)
        splitter.setSizes([290, 810])

    def _append_log(self, text: str):
        self.log.appendPlainText(text)

    # ------------------------------------------------------------------ スキャン
    def ensure_loaded(self):
        """画面を初めて開いたときだけスキャンする（起動を遅くしないため）。"""
        if not self._loaded:
            self.rescan()

    def rescan(self):
        target_python = self._target_python_getter()
        current_id = self._current_tool_id()
        try:
            self.result = service.run_tools_scan(self.paths, target_python)
        except (ScanError, ToolsRegistryError) as e:
            self._append_log(f"[エラー] {e}")
            QMessageBox.warning(self, "スキャン失敗", str(e))
            return
        self._loaded = True
        self.online_check.setChecked(self.result.registry.allow_online)
        self.python_label.setText(f"対象Python: {self.result.local_python_version}（{target_python}）")
        self._populate_tool_list(current_id)
        self._refresh_table()
        table = self.result.table
        self._append_log(f"スキャン完了: 登録ツール {len(table.tool_names)} 件 / ライブラリ {len(table.rows)} 件")

    def _populate_tool_list(self, keep_id: str | None):
        table = self.result.table
        self.tool_list.blockSignals(True)
        self.tool_list.clear()
        entries = [(ALL_TOOLS, "（全ツール合算）")] + list(table.tool_names.items())
        select_row = 0
        for i, (tid, name) in enumerate(entries):
            key = None if tid == ALL_TOOLS else tid
            if key in table.tool_errors:
                label, color = f"{name}  ✖読込エラー", "#a80000"
            else:
                pending = len(table.action_specs(key))
                conflicts = table.summary(key).get(LibStatus.CONFLICT, 0)
                marks = []
                if pending:
                    marks.append(f"要対応{pending}")
                if conflicts:
                    marks.append(f"競合{conflicts}")
                label = f"{name}  （{'・'.join(marks)}）" if marks else f"{name}  ✔"
                color = "#a80000" if pending else ("#795d00" if conflicts else "#0b6a0b")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, tid)
            item.setForeground(QBrush(QColor(color)))
            if tid != ALL_TOOLS:
                tool = self.result.registry.find(tid)
                item.setToolTip(f"{tool.description}\n{tool.requirements}" if tool and tool.description else (tool.requirements if tool else ""))
            self.tool_list.addItem(item)
            if tid == (keep_id or ALL_TOOLS):
                select_row = i
        self.tool_list.setCurrentRow(select_row)
        self.tool_list.blockSignals(False)

    def _current_tool_id(self) -> str | None:
        item = self.tool_list.currentItem()
        if item is None:
            return None
        tid = item.data(Qt.UserRole)
        return None if tid == ALL_TOOLS else tid

    # ------------------------------------------------------------------ 表示
    def _visible_rows(self) -> list[tuple[LibraryRow, RowEval]]:
        tool_id = self._current_tool_id()
        query = self.search_edit.text().strip().lower()
        out = []
        for row in self.result.table.rows:
            ev = row.evaluate(tool_id)
            if self.only_needed_check.isChecked() and not ev.needed:
                continue
            if self.only_action_check.isChecked() and not (ev.needed and (ev.status in ACTION_STATUSES or ev.status == LibStatus.CONFLICT)):
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
        tool_id = self._current_tool_id()
        self._refresh_summary(tool_id)

        rows = self._visible_rows()
        self._rows_cache = rows
        self.table.setRowCount(len(rows))
        bold = QFont()
        bold.setBold(True)
        for r, (row, ev) in enumerate(rows):
            bg, fg, status_label = STATUS_STYLE[ev.status]
            users = [table.tool_names[t] for t in row.reqs] + [f"{table.tool_names[t]}(対象外)" for t in row.excluded]
            values = [
                "★" if ev.needed else "",
                row.name,
                ev.specifier or ("(指定なし)" if ev.needed else ""),
                row.installed_version or "(未インストール)",
                status_label,
                ", ".join(users),
            ]
            tooltip = self._row_tooltip(row)
            for c, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(tooltip)
                if ev.needed:
                    cell.setBackground(QBrush(NEEDED_ROW_BG))
                    if c in (0, 1):
                        cell.setFont(bold)
                else:
                    cell.setForeground(QBrush(DIM_FG))
                if c == 4:
                    cell.setBackground(QBrush(QColor(bg)))
                    cell.setForeground(QBrush(QColor(fg)))
                    cell.setFont(bold)
                    cell.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    cell.setTextAlignment(Qt.AlignCenter)
                    cell.setForeground(QBrush(QColor("#c07a00")))
                if c == 5 and row.conflicts:
                    cell.setText("⚠ " + value)
                    cell.setForeground(QBrush(QColor("#795d00")))
                self.table.setItem(r, c, cell)

        can_act = tool_id not in table.tool_errors
        self.install_all_btn.setEnabled(can_act and bool(table.action_specs(tool_id)))
        self.remove_tool_btn.setEnabled(tool_id is not None)
        self.open_req_btn.setEnabled(tool_id is not None)

    def _row_tooltip(self, row: LibraryRow) -> str:
        names = self.result.table.tool_names
        lines = [f"{row.name}（インストール済: {row.installed_version or 'なし'}）"]
        for tid, req in row.reqs.items():
            lines.append(f"  {names[tid]}: {req.specifier or '指定なし'}  [{req.source}]")
        for tid, req in row.excluded.items():
            lines.append(f"  {names[tid]}: 環境マーカーによりこのPCでは対象外（{req.marker}）")
        if row.conflicts:
            lines.append("⚠ 競合:")
            lines += [f"  {m}" for m in row.conflicts]
        return "\n".join(lines)

    def _refresh_summary(self, tool_id: str | None):
        table = self.result.table
        counts = table.summary(tool_id)
        ok = sum(v for k, v in counts.items() if k in OK_STATUSES)
        parts = [f"<span style='background:#dff6dd;color:#0b6a0b;padding:2px 6px;'>&nbsp;OK {ok}&nbsp;</span>"]
        for status in SUMMARY_ORDER:
            n = counts.get(status, 0)
            if n:
                bg, fg, label = STATUS_STYLE[status]
                parts.append(f"<span style='background:{bg};color:{fg};'>&nbsp;{label} {n}&nbsp;</span>")
        name = table.tool_names.get(tool_id, "全ツール合算") if tool_id else "全ツール合算"
        self.summary_label.setText(f"<b>{name}</b>　必要ライブラリ {sum(counts.values())} 件：　" + "　".join(parts))

        notes = []
        if tool_id in table.tool_errors:
            notes.append(table.tool_errors[tool_id])
        ids = [tool_id] if tool_id else list(table.tool_warnings)
        for tid in ids:
            notes += [f"{table.tool_names[tid]}: {w}" for w in table.tool_warnings.get(tid, [])]
        if tool_id is None:
            notes += [f"{table.tool_names[t]}: {e}" for t, e in table.tool_errors.items()]
            if counts.get(LibStatus.CONFLICT):
                notes.insert(0, "競合しているライブラリは全ツール合算では導入できません。左の一覧でツールを選んで個別に導入してください。")
        self.warning_label.setText("\n".join(notes))
        self.warning_label.setVisible(bool(notes))

    # ------------------------------------------------------------------ 導入・更新
    def _spec_for(self, row: LibraryRow, ev: RowEval) -> str | None:
        if ev.install_spec:
            return ev.install_spec
        # 表示中のツールでは不要な行を選んだ場合は、全ツール合算の要件で導入する
        combined = row.evaluate(None)
        return combined.install_spec

    def install_selected(self, upgrade: bool, rows: list[int] | None = None):
        if self.result is None:
            return
        indexes = rows if rows is not None else sorted({i.row() for i in self.table.selectedIndexes()})
        if not indexes:
            QMessageBox.information(self, "未選択", "導入するライブラリの行を選択してください（Ctrl/Shiftで複数選択）。")
            return
        specs, skipped = [], []
        for i in indexes:
            row, ev = self._rows_cache[i]
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

    def _start_install(self, specs: list[str], upgrade: bool):
        if not specs:
            QMessageBox.information(self, "対象なし", "導入・更新が必要なライブラリはありません。")
            return
        downgrades = [
            row.name for row, ev in self._rows_cache
            if ev.status == LibStatus.NEWER and ev.install_spec in specs
        ]
        source = "共有ホイールハウス＋PyPI" if self.online_check.isChecked() else "共有ホイールハウスのみ（オフライン）"
        msg = (
            f"次の {len(specs)} 件を{'要件の範囲内で最新へ更新' if upgrade else '要件どおりに導入'}します。\n\n"
            + "\n".join(f"  ・{s}" for s in specs)
            + f"\n\n取得元: {source}\n対象Python: {self._target_python_getter()}"
        )
        if downgrades:
            msg += f"\n\n※ 次は要件より新しいため、要件のバージョンへ戻します（ダウングレード）: {', '.join(downgrades)}"
        if QMessageBox.question(self, "導入の確認", msg) != QMessageBox.Yes:
            return

        self._set_busy(True)
        self._append_log(f"{'更新' if upgrade else '導入'}を開始します（{source}）…")
        self._worker = ToolInstallWorker(
            self.paths, self._target_python_getter(), specs, self.online_check.isChecked(), upgrade,
        )
        self._worker.progress.connect(self._append_log)
        self._worker.finished_ok.connect(self._on_install_finished)
        self._worker.failed.connect(self._on_install_failed)
        self._worker.start()

    def _on_install_finished(self, results):
        ng = [r for r in results if not r.success]
        for r in results:
            self._append_log(f"  [{'OK' if r.success else 'NG'}] {r.name}: {r.message}")
        self._set_busy(False)
        self.rescan()
        if ng:
            hint = "" if self.online_check.isChecked() else "\n\n共有ホイールハウスに該当の .whl が無い場合は「PyPIからも取得」をONにしてください。"
            QMessageBox.warning(self, "一部失敗", f"{len(ng)} 件の導入に失敗しました。ログを確認してください。{hint}")

    def _on_install_failed(self, message: str):
        self._set_busy(False)
        self._append_log(f"[エラー] 導入に失敗しました: {message}")
        QMessageBox.warning(self, "導入失敗", message)

    def _set_busy(self, busy: bool):
        for w in (self.rescan_btn, self.install_sel_btn, self.upgrade_sel_btn, self.install_all_btn,
                  self.add_tool_btn, self.remove_tool_btn):
            w.setEnabled(not busy)
        self.table.setEnabled(not busy)

    # ------------------------------------------------------------------ ツール登録
    def add_tool(self):
        dlg = RegisterToolDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            entry = tools_registry.register_tool(
                self.paths, dlg.name_edit.text(), Path(dlg.path_edit.text().strip()),
                description=dlg.desc_edit.text(), copy_to_runtime=dlg.copy_check.isChecked(),
            )
        except ToolsRegistryError as e:
            QMessageBox.warning(self, "登録失敗", str(e))
            return
        self._append_log(f"ツールを登録しました: {entry.name}（{entry.requirements}）")
        self.rescan()
        self._select_tool(entry.id)

    def remove_tool(self):
        tool_id = self._current_tool_id()
        if tool_id is None:
            return
        name = self.result.table.tool_names.get(tool_id, tool_id)
        if QMessageBox.question(
            self, "登録解除の確認",
            f"「{name}」を登録簿から外します（requirements.txt 自体は削除しません）。よろしいですか？",
        ) != QMessageBox.Yes:
            return
        try:
            tools_registry.unregister_tool(self.paths, tool_id)
        except ToolsRegistryError as e:
            QMessageBox.warning(self, "登録解除失敗", str(e))
            return
        self._append_log(f"登録を解除しました: {name}")
        self.rescan()

    def open_requirements(self):
        tool_id = self._current_tool_id()
        tool = self.result.registry.find(tool_id) if (self.result and tool_id) else None
        if tool is None:
            return
        path = tools_registry.resolve_requirements_path(self.paths, tool)
        if not path.exists():
            QMessageBox.warning(self, "ファイルなし", f"見つかりません: {path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _select_tool(self, tool_id: str):
        for i in range(self.tool_list.count()):
            if self.tool_list.item(i).data(Qt.UserRole) == tool_id:
                self.tool_list.setCurrentRow(i)
                return
