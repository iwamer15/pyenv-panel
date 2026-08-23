"""Python本体のサイレントインストール機能。

前提:
  - runtime/config/manifest.json の python.installer_path が、共有サーバ上の
    python.org公式インストーラ（例: python-3.11.9-amd64.exe）を指している。
  - インストーラをUNCパス上から直接実行するとネットワーク越しの実行になり不安定なため、
    まずローカルの一時フォルダにコピーしてから実行する。
  - 既存の「業務で使うPython」（PATH上のpython等）とは分離し、
    このツール専用のローカル領域（%LOCALAPPDATA%\\PyEnvPanel\\python\\<version>\\）に
    サイレントインストールする。他アプリへの影響やPATH汚染を避けるため
    InstallAllUsers=0 / PrependPath=0 とする。

python.org公式インストーラの主なサイレントオプション（参考）:
  /quiet                 UIを出さずに実行
  InstallAllUsers=0      現在のユーザーのみにインストール（管理者権限不要）
  PrependPath=0          システムPATHは変更しない（このツールが対象Pythonのパスを管理するため）
  Include_launcher=0     py.exeランチャーは入れない（衝突回避）
  Include_test=0         テストスイートは含めない（容量削減）
  TargetDir=<path>       インストール先を明示的に指定
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import RuntimePaths
from .manifest import ManifestData
from .scanner import ScanError, get_local_python_version


class PythonInstallError(Exception):
    pass


@dataclass
class PythonInstallResult:
    success: bool
    python_exe: Path | None
    message: str


def local_python_install_dir(version: str) -> Path:
    """このツールが管理するPython本体の既定インストール先。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "PyEnvPanel" / "python" / version


def _python_exe_path(install_dir: Path) -> Path:
    # Windows版インストーラは install_dir 直下に python.exe を配置する
    return install_dir / "python.exe"


def install_python_silently(
    paths: RuntimePaths,
    manifest: ManifestData,
    progress_cb: Callable[[str], None] | None = None,
    timeout: int = 900,
) -> PythonInstallResult:
    def report(msg: str):
        if progress_cb:
            progress_cb(msg)

    if not manifest.python_installer_path:
        return PythonInstallResult(False, None, "マニフェストに python.installer_path が設定されていません。")

    installer_src = paths.root / manifest.python_installer_path
    if not installer_src.exists():
        return PythonInstallResult(
            False, None,
            f"共有サーバ上にインストーラが見つかりません: {installer_src}",
        )

    install_dir = local_python_install_dir(manifest.python_version)
    target_python = _python_exe_path(install_dir)

    # 既に同バージョンが導入済みならインストールをスキップ
    if target_python.exists():
        try:
            existing_version = get_local_python_version(str(target_python))
            if existing_version == manifest.python_version:
                report(f"既に {manifest.python_version} がインストール済みです: {target_python}")
                return PythonInstallResult(True, target_python, "既存のインストールを使用しました。")
        except ScanError:
            pass  # 壊れている場合は再インストールへ続行

    report(f"インストーラをローカルにコピー中... ({installer_src.name})")
    with tempfile.TemporaryDirectory(prefix="pyenv_panel_installer_") as tmp_dir:
        local_installer = Path(tmp_dir) / installer_src.name
        try:
            shutil.copyfile(installer_src, local_installer)
        except OSError as e:
            return PythonInstallResult(False, None, f"インストーラのコピーに失敗しました: {e}")

        install_dir.mkdir(parents=True, exist_ok=True)
        report(f"サイレントインストール実行中... (対象: {install_dir})")

        cmd = [
            str(local_installer),
            "/quiet",
            "InstallAllUsers=0",
            "PrependPath=0",
            "Include_launcher=0",
            "Include_test=0",
            f"TargetDir={install_dir}",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            return PythonInstallResult(False, None, f"インストーラの実行に失敗しました: {e}")

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()
            return PythonInstallResult(
                False, None,
                f"インストーラが異常終了しました（終了コード {proc.returncode}）: {tail[-500:]}",
            )

    if not target_python.exists():
        return PythonInstallResult(False, None, f"インストール後にpython.exeが見つかりません: {target_python}")

    try:
        installed_version = get_local_python_version(str(target_python))
    except ScanError as e:
        return PythonInstallResult(False, None, f"インストール後のバージョン確認に失敗しました: {e}")

    if installed_version != manifest.python_version:
        return PythonInstallResult(
            False, target_python,
            f"インストールは完了しましたが、バージョンが一致しません（要求: {manifest.python_version} / 実際: {installed_version}）",
        )

    report(f"インストール完了・バージョン確認OK: {installed_version}")
    return PythonInstallResult(True, target_python, "インストール完了")
