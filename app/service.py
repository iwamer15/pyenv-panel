"""GUI/CLIどちらからも呼び出せる、機能をまとめたサービス層。"""
from __future__ import annotations

from pathlib import Path

from dataclasses import dataclass

from . import scanner, status, tools_registry
from .config import RuntimePaths, write_user_config
from .manifest import ManifestData, ManifestError, load_manifest
from .models import ScanReport, SyncResult
from .python_installer import PythonInstallResult, install_python_silently
from .requirements_file import RequirementsFileError, parse_requirements_file
from .syncer import install_specs, sync_packages
from .tool_compare import LibraryTable, build_library_table


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


# ---------------------------------------------------------------------------
# ツール別ライブラリ（登録ツールの requirements.txt と実環境の比較）
# ---------------------------------------------------------------------------

@dataclass
class ToolsScanResult:
    registry: tools_registry.ToolsRegistry
    table: LibraryTable
    local_python_version: str
    target_python: str


def run_tools_scan(paths: RuntimePaths, target_python: str) -> ToolsScanResult:
    registry = tools_registry.load_registry(paths)

    tool_reqs, warnings, errors = {}, {}, {}
    for tool in registry.tools:
        try:
            parsed = parse_requirements_file(tools_registry.resolve_requirements_path(paths, tool))
        except RequirementsFileError as e:
            errors[tool.id] = str(e)
            continue
        tool_reqs[tool.id] = parsed.requirements
        if parsed.warnings:
            warnings[tool.id] = parsed.warnings

    local_version = scanner.get_local_python_version(target_python)
    installed = scanner.get_installed_packages(target_python)
    marker_env = scanner.get_marker_environment(target_python)

    table = build_library_table(
        tool_reqs,
        {t.id: t.name for t in registry.tools},
        installed,
        marker_env=marker_env,
        tool_warnings=warnings,
        tool_errors=errors,
    )
    return ToolsScanResult(registry, table, local_version, target_python)


def resolve_wheels_dir(paths: RuntimePaths) -> Path:
    """マニフェストの wheelhouse 設定を優先し、読めなければ runtime/wheels を使う。"""
    try:
        wheelhouse = Path(load_manifest(paths.manifest_path).wheelhouse_dir_name)
    except ManifestError:
        return paths.wheels_dir
    return wheelhouse if wheelhouse.is_absolute() else paths.root / wheelhouse


def run_tool_install(
    paths: RuntimePaths,
    target_python: str,
    specs: list[str],
    allow_online: bool,
    upgrade: bool = False,
    progress_cb=None,
) -> list[SyncResult]:
    return install_specs(
        target_python, specs, resolve_wheels_dir(paths),
        allow_online=allow_online, upgrade=upgrade, progress_cb=progress_cb,
    )
