"""管理者モードから runtime/config/manifest.json を編集するダイアログ。

README「実運用に向けて」の TODO の一つ:
    「管理者モードからのマニフェスト編集UI（現状は手動でJSON編集する想定）」

に対応する。生JSON全体（python / packages / groups）を読み込み、
基本設定・パッケージ一覧・グループ定義の3タブで編集し、保存時に
manifest.validate_raw_manifest() で整合性チェックしてから書き戻す。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..manifest import ManifestError, load_raw_manifest, save_raw_manifest


class ManifestEditorDialog(QDialog):
    def __init__(self, manifest_path: Path, parent=None):
        super().__init__(parent)
        self.manifest_path = manifest_path
        self.setWindowTitle(f"マニフェスト編集 - {manifest_path}")
        self.resize(700, 500)

        try:
            self._raw = load_raw_manifest(manifest_path)
        except ManifestError as e:
            self._raw = {
                "schema_version": 1,
                "python": {"version": "", "installer_path": ""},
                "packages": [],
                "wheelhouse": "wheels",
                "groups": {"default": {"packages": []}},
            }
            QMessageBox.warning(self, "読み込みエラー", f"{e}\n\n新規テンプレートを表示します。")

        self._build_ui()
        self._load_into_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        self.tabs.addTab(self._build_basic_tab(), "基本設定")
        self.tabs.addTab(self._build_packages_tab(), "パッケージ一覧")
        self.tabs.addTab(self._build_groups_tab(), "グループ")

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_basic_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Pythonバージョン（例: 3.11.9）"))
        self.python_version_edit = QLineEdit()
        layout.addWidget(self.python_version_edit)

        layout.addWidget(QLabel("Pythonインストーラの相対パス（共有ランタイムルートからの相対、例: python/3.11.9/python-3.11.9-amd64.exe）"))
        self.installer_path_edit = QLineEdit()
        layout.addWidget(self.installer_path_edit)

        layout.addWidget(QLabel("wheelhouseディレクトリ名（既定: wheels）"))
        self.wheelhouse_edit = QLineEdit()
        layout.addWidget(self.wheelhouse_edit)

        layout.addStretch(1)
        return w

    def _build_packages_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("組織標準ライブラリの一覧（全グループが参照するマスタ）"))

        self.packages_table = QTableWidget(0, 2)
        self.packages_table.setHorizontalHeaderLabels(["パッケージ名", "バージョン"])
        self.packages_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.packages_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout.addWidget(self.packages_table, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("行を追加")
        remove_btn = QPushButton("選択行を削除")
        add_btn.clicked.connect(lambda: self._add_table_row(self.packages_table, ["", ""]))
        remove_btn.clicked.connect(lambda: self._remove_selected_rows(self.packages_table))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        return w

    def _build_groups_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(
            "配布グループの定義。「パッケージ」列はパッケージ一覧タブのパッケージ名をカンマ区切りで指定します。\n"
            "「継承元」は親グループ名（任意）。端末モードは既定で 'default' グループを使用します。"
        ))

        self.groups_table = QTableWidget(0, 3)
        self.groups_table.setHorizontalHeaderLabels(["グループ名", "継承元(extends)", "パッケージ（カンマ区切り）"])
        self.groups_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.groups_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.groups_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.groups_table, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("行を追加")
        remove_btn = QPushButton("選択行を削除")
        add_btn.clicked.connect(lambda: self._add_table_row(self.groups_table, ["", "", ""]))
        remove_btn.clicked.connect(lambda: self._remove_selected_rows(self.groups_table))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        return w

    @staticmethod
    def _add_table_row(table: QTableWidget, values: list[str]):
        row = table.rowCount()
        table.insertRow(row)
        for col, value in enumerate(values):
            table.setItem(row, col, QTableWidgetItem(value))

    @staticmethod
    def _remove_selected_rows(table: QTableWidget):
        rows = sorted({idx.row() for idx in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    def _load_into_ui(self):
        python_raw = self._raw.get("python", {})
        self.python_version_edit.setText(python_raw.get("version", ""))
        self.installer_path_edit.setText(python_raw.get("installer_path", ""))
        self.wheelhouse_edit.setText(self._raw.get("wheelhouse", "wheels"))

        self.packages_table.setRowCount(0)
        for p in self._raw.get("packages", []):
            self._add_table_row(self.packages_table, [p.get("name", ""), p.get("version", "")])

        self.groups_table.setRowCount(0)
        for name, g in self._raw.get("groups", {}).items():
            packages_csv = ", ".join(g.get("packages", []))
            self._add_table_row(self.groups_table, [name, g.get("extends", "") or "", packages_csv])

    def _collect_from_ui(self) -> dict:
        raw = dict(self._raw)  # schema_version 等、UIに出さない項目を引き継ぐ

        raw["python"] = {
            "version": self.python_version_edit.text().strip(),
            "installer_path": self.installer_path_edit.text().strip(),
        }
        raw["wheelhouse"] = self.wheelhouse_edit.text().strip() or "wheels"

        packages = []
        for row in range(self.packages_table.rowCount()):
            name_item = self.packages_table.item(row, 0)
            version_item = self.packages_table.item(row, 1)
            name = (name_item.text().strip() if name_item else "")
            version = (version_item.text().strip() if version_item else "")
            if not name and not version:
                continue  # 完全に空の行は無視
            packages.append({"name": name, "version": version})
        raw["packages"] = packages

        groups = {}
        for row in range(self.groups_table.rowCount()):
            name_item = self.groups_table.item(row, 0)
            extends_item = self.groups_table.item(row, 1)
            pkgs_item = self.groups_table.item(row, 2)
            name = (name_item.text().strip() if name_item else "")
            if not name:
                continue
            extends = (extends_item.text().strip() if extends_item else "")
            pkgs_csv = (pkgs_item.text().strip() if pkgs_item else "")
            pkg_names = [n.strip() for n in pkgs_csv.split(",") if n.strip()]
            entry: dict = {"packages": pkg_names}
            if extends:
                entry["extends"] = extends
            groups[name] = entry
        raw["groups"] = groups

        return raw

    def _on_save(self):
        raw = self._collect_from_ui()
        try:
            save_raw_manifest(self.manifest_path, raw)
        except ManifestError as e:
            QMessageBox.warning(self, "保存できません", str(e))
            return
        QMessageBox.information(self, "保存完了", f"マニフェストを保存しました:\n{self.manifest_path}")
        self.accept()
