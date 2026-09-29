"""端末モード画面。

設計書 5.1 節に対応:
  - 上部: Pythonバージョン / マニフェスト更新日時 / 準拠状況バッジ
  - 中央: ライブラリ一覧テーブル（パッケージ名 / 要求バージョン / インストール済 / 状態）
  - 下部: 「再スキャン」「まとめて同期」ボタン、実行ログ
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import service
from ..config import RuntimePaths
from ..manifest import ManifestError
from ..models import DiffStatus, ManifestData, ScanReport
from ..scanner import ScanError

STATUS_COLORS = {
    DiffStatus.OK: QColor("#dff6dd"),
    DiffStatus.MISSING: QColor("#fde7e9"),
    DiffStatus.VERSION_MISMATCH: QColor("#fff4ce"),
}


class SyncWorker(QThread):
    progress = Signal(str)
    finished_ok = Signal(list, object)  # results, refreshed_report
    failed = Signal(str)

    def __init__(self, paths: RuntimePaths, target_python: str, manifest: ManifestData, report: ScanReport):
        super().__init__()
        self._paths = paths
        self._target_python = target_python
        self._manifest = manifest
        self._report = report

    def run(self):
        try:
            results, refreshed = service.run_sync_and_report(
                self._paths, self._target_python, self._manifest, self._report,
                progress_cb=self.progress.emit,
            )
            self.finished_ok.emit(results, refreshed)
        except Exception as e:  # noqa: BLE001 - UIに伝える
            self.failed.emit(str(e))


class PythonInstallWorker(QThread):
    progress = Signal(str)
    finished_ok = Signal(object)  # PythonInstallResult
    failed = Signal(str)

    def __init__(self, paths: RuntimePaths, manifest: ManifestData):
        super().__init__()
        self._paths = paths
        self._manifest = manifest

    def run(self):
        try:
            result = service.run_python_install(self._paths, self._manifest, progress_cb=self.progress.emit)
            self.finished_ok.emit(result)
        except Exception as e:  # noqa: BLE001 - UIに伝える
            self.failed.emit(str(e))


class TerminalView(QWidget):
    def __init__(self, paths: RuntimePaths, target_python: str, group: str = "default", parent=None):
        super().__init__(parent)
        self.paths = paths
        self.target_python = target_python
        self.group = group
        self.manifest: ManifestData | None = None
        self.report: ScanReport | None = None
        self._worker: SyncWorker | None = None
        self._python_worker: PythonInstallWorker | None = None

        self._build_ui()
        self.rescan()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        title = QLabel("このPCの標準構成")
        title.setObjectName("h1")
        root.addWidget(title)
        desc = QLabel("組織標準（マニフェスト）で決められたPython・ライブラリと、このPCの状態を比べます。"
                      "「まとめて同期」で共有フォルダの .whl から不足分を導入します。")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        root.addWidget(desc)

        info_row = QHBoxLayout()
        self.python_label = QLabel("Pythonバージョン: -")
        self.manifest_label = QLabel("マニフェスト更新: -")
        self.badge_label = QLabel("状態: -")
        self.badge_label.setStyleSheet("font-weight: bold; padding: 2px 10px; border-radius: 4px;")
        for w in (self.python_label, self.manifest_label):
            info_row.addWidget(w)
        info_row.addStretch(1)
        info_row.addWidget(self.badge_label)
        root.addLayout(info_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["パッケージ名", "要求バージョン", "インストール済", "状態"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setShowGrid(False)
        root.addWidget(self.table, stretch=1)

        btn_row = QHBoxLayout()
        self.rescan_btn = QPushButton("⟳ 再スキャン")
        self.sync_btn = QPushButton("まとめて同期")
        self.sync_btn.setObjectName("primary")
        self.install_python_btn = QPushButton("Pythonをインストール")
        self.install_python_btn.setVisible(False)
        self.rescan_btn.clicked.connect(self.rescan)
        self.sync_btn.clicked.connect(self.sync_all)
        self.install_python_btn.clicked.connect(self.install_python)
        btn_row.addWidget(self.rescan_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.install_python_btn)
        btn_row.addWidget(self.sync_btn)
        root.addLayout(btn_row)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setFixedHeight(120)
        root.addWidget(self.log)

    def _append_log(self, text: str):
        self.log.appendPlainText(text)

    def rescan(self):
        if not self.paths.manifest_path.exists():
            # 新しく作った共有フォルダ等。エラーダイアログは出さず、画面内で案内する
            self.manifest = self.report = None
            self.table.setRowCount(0)
            self.python_label.setText("組織標準（マニフェスト）が未設定です")
            self.manifest_label.setText("管理者画面の「マニフェスト編集」で作成できます")
            self.badge_label.setText("状態: 未設定")
            self.badge_label.setStyleSheet("font-weight: bold; padding: 2px 10px; border-radius: 4px; background:#f1f5f9; color:#64748b;")
            self.install_python_btn.setVisible(False)
            return
        try:
            self.manifest, self.report = service.run_scan(self.paths, self.target_python, group=self.group)
        except (ManifestError, ScanError) as e:
            self._append_log(f"[エラー] {e}")
            QMessageBox.warning(self, "スキャン失敗", str(e))
            return

        self._refresh_labels()
        self._refresh_table()
        self._append_log(f"[{self.report.checked_at}] スキャン完了（不足 {self.report.missing_count} / 不一致 {self.report.mismatch_count}）")

    def _refresh_labels(self):
        m, r = self.manifest, self.report
        self.python_label.setText(f"Pythonバージョン: {r.local_python_version}（要求: {m.python_version}）")
        self.manifest_label.setText(f"マニフェスト更新: {m.updated_at}（グループ: {m.group}）")
        if r.compliant:
            self.badge_label.setText("状態: 準拠 OK")
            self.badge_label.setStyleSheet(self.badge_label.styleSheet() + "background-color:#dff6dd; color:#0b6a0b;")
        else:
            self.badge_label.setText("状態: 要同期")
            self.badge_label.setStyleSheet(self.badge_label.styleSheet() + "background-color:#fde7e9; color:#a80000;")

        self.install_python_btn.setVisible(not r.python_compliant)

    def _refresh_table(self):
        items = self.report.diff_items
        self.table.setRowCount(len(items))
        for row, d in enumerate(items):
            values = [d.name, d.required_version, d.installed_version or "(未インストール)", d.status.value]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setBackground(STATUS_COLORS.get(d.status, QColor("white")))
                if col == 3:
                    cell.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, cell)

    def sync_all(self):
        if not self.manifest or not self.report:
            return
        if self.report.compliant:
            QMessageBox.information(self, "同期不要", "既にマニフェストへ準拠しています。")
            return

        self.sync_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self._append_log("同期を開始します…")

        self._worker = SyncWorker(self.paths, self.target_python, self.manifest, self.report)
        self._worker.progress.connect(self._append_log)
        self._worker.finished_ok.connect(self._on_sync_finished)
        self._worker.failed.connect(self._on_sync_failed)
        self._worker.start()

    def _on_sync_finished(self, results, refreshed_report):
        self.report = refreshed_report
        for r in results:
            mark = "OK" if r.success else "NG"
            self._append_log(f"  [{mark}] {r.name}=={r.version}: {r.message}")
        self._refresh_labels()
        self._refresh_table()
        self._append_log("同期処理が完了しました。状態レポートを共有サーバへ送信しました。")
        self.sync_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)

    def _on_sync_failed(self, message: str):
        self._append_log(f"[エラー] 同期に失敗しました: {message}")
        QMessageBox.warning(self, "同期失敗", message)
        self.sync_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)

    def install_python(self):
        if not self.manifest:
            return
        reply = QMessageBox.question(
            self, "Pythonインストール確認",
            f"マニフェスト指定のPython {self.manifest.python_version} を、このツール専用の"
            "ローカル領域にサイレントインストールします。よろしいですか？\n"
            "（既存のPATH上のPythonには影響しません）",
        )
        if reply != QMessageBox.Yes:
            return

        self.install_python_btn.setEnabled(False)
        self.sync_btn.setEnabled(False)
        self.rescan_btn.setEnabled(False)
        self._append_log("Python本体のインストールを開始します…")

        self._python_worker = PythonInstallWorker(self.paths, self.manifest)
        self._python_worker.progress.connect(self._append_log)
        self._python_worker.finished_ok.connect(self._on_python_install_finished)
        self._python_worker.failed.connect(self._on_python_install_failed)
        self._python_worker.start()

    def _on_python_install_finished(self, result):
        self.install_python_btn.setEnabled(True)
        self.sync_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)
        if result.success and result.python_exe is not None:
            self._append_log(f"Pythonインストール成功: {result.python_exe}")
            self.target_python = str(result.python_exe)
            self.rescan()
        else:
            self._append_log(f"[エラー] Pythonインストール失敗: {result.message}")
            QMessageBox.warning(self, "インストール失敗", result.message)

    def _on_python_install_failed(self, message: str):
        self.install_python_btn.setEnabled(True)
        self.sync_btn.setEnabled(True)
        self.rescan_btn.setEnabled(True)
        self._append_log(f"[エラー] Pythonインストールに失敗しました: {message}")
        QMessageBox.warning(self, "インストール失敗", message)
