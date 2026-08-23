"""GUI/CLIどちらからも呼び出せる、機能をまとめたサービス層。"""
from __future__ import annotations

from pathlib import Path

from . import scanner, status
from .config import RuntimePaths, write_user_config
from .manifest import ManifestData, load_manifest
from .models import ScanReport
from .python_installer import PythonInstallResult, install_python_silently
from .syncer import sync_packages


def run_scan(paths: RuntimePaths, target_python: str, group: str = "default") -> tuple[ManifestData, ScanReport]:
    manifest = load_manifest(paths.manifest_path, group=group)

    local_version = scanner.get_local_python_version(target_python)
    installed = scanner.get_installed_packages(target_python)
    diff_items = scanner.compute_diff(manifest, installed)
    extra_count = scanner.count_extra_packages(manifest, installed)

    report = ScanReport(
        hostname=status.current_hostname(),
        user=status.current_user(),
        checked_at=status.now_iso(),
        local_python_version=local_version,
        manifest_python_version=manifest.python_version,
        python_compliant=(local_version == manifest.python_version),
        diff_items=diff_items,
        extra_package_count=extra_count,
    )
    return manifest, report


def run_sync_and_report(
    paths: RuntimePaths,
    target_python: str,
    manifest: ManifestData,
    report: ScanReport,
    progress_cb=None,
):
    wheelhouse = Path(manifest.wheelhouse_dir_name)
    wheels_dir = wheelhouse if wheelhouse.is_absolute() else paths.root / manifest.wheelhouse_dir_name

    results = sync_packages(target_python, wheels_dir, report.diff_items, progress_cb=progress_cb)

    # 再スキャンして最新状態を反映
    _, refreshed_report = run_scan(paths, target_python, group=manifest.group)
    refreshed_report.last_sync_at = status.now_iso()
    status.write_status_report(paths.status_dir, refreshed_report)
    return results, refreshed_report


def run_python_install(paths: RuntimePaths, manifest: ManifestData, progress_cb=None) -> PythonInstallResult:
    """マニフェストの要求バージョンでPython本体をサイレントインストールし、
    成功した場合は以降このツールが使う対象PythonをローカルAPPDATA配下の
    インストール先に切り替える（config.iniへ保存）。"""
    result = install_python_silently(paths, manifest, progress_cb=progress_cb)
    if result.success and result.python_exe is not None:
        write_user_config(root=str(paths.root), target_python=str(result.python_exe))
    return result
