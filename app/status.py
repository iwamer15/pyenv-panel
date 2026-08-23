"""端末の自己診断結果を runtime/status/<hostname>.json に書き込み／読み込みする。

管理者モードはこの status/ 配下を集計して組織全体の準拠状況を表示する。
"""
from __future__ import annotations

import getpass
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

from .models import DiffStatus, ScanReport


def current_hostname() -> str:
    return socket.gethostname()


def current_user() -> str:
    return getpass.getuser()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def report_to_dict(report: ScanReport) -> dict:
    return {
        "hostname": report.hostname,
        "user": report.user,
        "checked_at": report.checked_at,
        "local_python_version": report.local_python_version,
        "manifest_python_version": report.manifest_python_version,
        "python_compliant": report.python_compliant,
        "compliant": report.compliant,
        "missing_count": report.missing_count,
        "mismatch_count": report.mismatch_count,
        "extra_package_count": report.extra_package_count,
        "last_sync_at": report.last_sync_at,
        "diff_items": [
            {
                "name": d.name,
                "required_version": d.required_version,
                "installed_version": d.installed_version,
                "status": d.status.value,
            }
            for d in report.diff_items
        ],
    }


def write_status_report(status_dir: Path, report: ScanReport) -> Path:
    status_dir.mkdir(parents=True, exist_ok=True)
    out_path = status_dir / f"{report.hostname}.json"
    out_path.write_text(
        json.dumps(report_to_dict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def read_all_status_reports(status_dir: Path) -> list[dict]:
    if not status_dir.exists():
        return []
    reports = []
    for path in sorted(status_dir.glob("*.json")):
        try:
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            # 壊れたレポートは無視して読み進める（他端末の集計に影響させない）
            continue
    return reports
