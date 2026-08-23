"""管理者モード画面。

設計書 5.2 節に対応:
  - 上部: 組織全体の準拠率、未同期端末数のサマリ
  - 中央: 端末一覧テーブル（端末名 / 利用者 / Pythonバージョン / 準拠状況 / 不足・不一致件数 / 最終同期日時）
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..config import RuntimePaths
from ..status import read_all_status_reports

COLUMNS = ["端末名", "利用者", "Pythonバージョン", "準拠状況", "不足件数", "不一致件数", "最終同期日時"]


class AdminView(QWidget):
    def __init__(self, paths: RuntimePaths, parent=None):
        super().__init__(parent)
        self.paths = paths
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)

        summary_row = QHBoxLayout()
        self.summary_label = QLabel("組織全体の準拠率: -")
        self.summary_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        self.unsynced_label = QLabel("未準拠端末数: -")
        refresh_btn = QPushButton("更新")
        refresh_btn.clicked.connect(self.refresh)
        summary_row.addWidget(self.summary_label)
        summary_row.addSpacing(20)
        summary_row.addWidget(self.unsynced_label)
        summary_row.addStretch(1)
        summary_row.addWidget(refresh_btn)
        root.addLayout(summary_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, len(COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        root.addWidget(self.table, stretch=1)

    def refresh(self):
        reports = read_all_status_reports(self.paths.status_dir)
        self.table.setRowCount(len(reports))

        compliant_count = 0
        for row, rep in enumerate(reports):
            compliant = bool(rep.get("compliant"))
            compliant_count += 1 if compliant else 0
            values = [
                rep.get("hostname", "-"),
                rep.get("user", "-"),
                rep.get("local_python_version", "-"),
                "準拠" if compliant else "要同期",
                str(rep.get("missing_count", 0)),
                str(rep.get("mismatch_count", 0)),
                rep.get("last_sync_at") or rep.get("checked_at") or "-",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 3:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setBackground(QColor("#dff6dd") if compliant else QColor("#fde7e9"))
                self.table.setItem(row, col, item)

        total = len(reports)
        rate = (compliant_count / total * 100) if total else 0.0
        self.summary_label.setText(f"組織全体の準拠率: {rate:.0f}%（{compliant_count}/{total}端末）")
        self.unsynced_label.setText(f"未準拠端末数: {total - compliant_count}")
