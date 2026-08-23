"""データモデル定義。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DiffStatus(str, Enum):
    OK = "OK"
    MISSING = "未インストール"
    VERSION_MISMATCH = "バージョン不一致"


@dataclass
class PackageRequirement:
    name: str
    version: str


@dataclass
class ManifestData:
    schema_version: int
    updated_at: str
    python_version: str
    python_installer_path: str
    packages: list[PackageRequirement]
    wheelhouse_dir_name: str
    group: str


@dataclass
class DiffItem:
    name: str
    required_version: str
    installed_version: str | None
    status: DiffStatus

    @property
    def needs_action(self) -> bool:
        return self.status != DiffStatus.OK


@dataclass
class SyncResult:
    name: str
    version: str
    success: bool
    message: str


@dataclass
class ScanReport:
    hostname: str
    user: str
    checked_at: str
    local_python_version: str
    manifest_python_version: str
    python_compliant: bool
    diff_items: list[DiffItem]
    extra_package_count: int
    last_sync_at: str | None = None

    @property
    def missing_count(self) -> int:
        return sum(1 for d in self.diff_items if d.status == DiffStatus.MISSING)

    @property
    def mismatch_count(self) -> int:
        return sum(1 for d in self.diff_items if d.status == DiffStatus.VERSION_MISMATCH)

    @property
    def compliant(self) -> bool:
        return self.python_compliant and all(d.status == DiffStatus.OK for d in self.diff_items)
