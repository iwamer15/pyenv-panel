"""共有ランタイムルート（runtime/）の場所を解決するモジュール。

本番環境では共有サーバのUNCパス（例: \\\\fileserver\\share\\runtime）を既定値とし、
IT管理者が %APPDATA%\\PyEnvPanel\\config.ini で上書きできるようにする。
このプロトタイプでは、開発・動作確認用に環境変数 / ローカルのsample_runtimeへ
フォールバックする。

解決の優先順位:
  1. 環境変数 PYENV_PANEL_RUNTIME_ROOT
  2. %APPDATA%\\PyEnvPanel\\config.ini の [runtime] root=...
  3. 本番既定値 DEFAULT_RUNTIME_ROOT（UNCパス、環境に存在しなければスキップ）
  4. 開発フォールバック: リポジトリ同梱の sample_runtime/
"""
from __future__ import annotations

import configparser
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

# 本番運用時の既定値（実際の組織のファイルサーバ名に置き換える）
DEFAULT_RUNTIME_ROOT = r"\\fileserver\share\runtime"

APP_NAME = "PyEnvPanel"
ENV_VAR = "PYENV_PANEL_RUNTIME_ROOT"
TARGET_PYTHON_ENV_VAR = "PYENV_PANEL_TARGET_PYTHON"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "config" / "manifest.json"

    @property
    def python_dir(self) -> Path:
        return self.root / "python"

    @property
    def wheels_dir(self) -> Path:
        return self.root / "wheels"

    @property
    def status_dir(self) -> Path:
        return self.root / "status"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"


def _user_config_ini_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(appdata) / APP_NAME / "config.ini"


def _read_from_ini(section: str, key: str) -> str | None:
    ini_path = _user_config_ini_path()
    if not ini_path.exists():
        return None
    parser = configparser.ConfigParser()
    try:
        parser.read(ini_path, encoding="utf-8")
        return parser.get(section, key, fallback=None)
    except (configparser.Error, OSError):
        return None


def _dev_fallback_root() -> Path:
    # このファイル (app/config.py) から見て ../sample_runtime
    return Path(__file__).resolve().parent.parent / "sample_runtime"


def resolve_runtime_root() -> RuntimePaths:
    """共有ランタイムルートを解決する。存在確認まではしない（呼び出し側でハンドリング）。"""
    env_value = os.environ.get(ENV_VAR)
    if env_value:
        return RuntimePaths(Path(env_value))

    ini_value = _read_from_ini("runtime", "root")
    if ini_value:
        return RuntimePaths(Path(ini_value))

    default_path = Path(DEFAULT_RUNTIME_ROOT)
    if default_path.exists():
        return RuntimePaths(default_path)

    # exe化した場合: exeと同じフォルダの runtime/ → sample_runtime/ を探す
    # （配布zipを展開してそのまま起動したときに設定なしで動くようにする）
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for name in ("runtime", "sample_runtime"):
            if (exe_dir / name).is_dir():
                return RuntimePaths(exe_dir / name)

    # 開発・デモ用フォールバック（共有サーバに接続できない環境向け）
    return RuntimePaths(_dev_fallback_root())


def resolve_target_python() -> str:
    """このツールが「管理対象」とするpython実行ファイルのパスを解決する。

    重要: このパネルツール自身が PyInstaller 等でexe化された場合、
    sys.executable はツール自身の実行ファイルであり「業務で使うPython」ではない。
    そのため既定では PATH 上の python を探す。組織で複数バージョンを使い分ける場合は
    config.ini の [target] python=... で明示するか、環境変数で指定する。
    """
    env_value = os.environ.get(TARGET_PYTHON_ENV_VAR)
    if env_value:
        return env_value

    ini_value = _read_from_ini("target", "python")
    if ini_value:
        return ini_value

    found = shutil.which("python") or shutil.which("python3")
    if found:
        return found

    # 最終フォールバック（開発環境でのデモ用）
    return sys.executable


def is_env_overridden(kind: str) -> bool:
    """環境変数で指定されている場合、GUIからの変更（config.ini）は効かないため画面で知らせる。"""
    return bool(os.environ.get(ENV_VAR if kind == "runtime" else TARGET_PYTHON_ENV_VAR))


def write_user_config(root: str | None = None, target_python: str | None = None) -> Path:
    """管理者/利用者がGUIから明示的にランタイムルート等を変更した際に保存する。
    None の項目は既存の値を変更しない。"""
    ini_path = _user_config_ini_path()
    ini_path.parent.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser()
    parser.read(ini_path, encoding="utf-8") if ini_path.exists() else None
    if root:
        parser["runtime"] = {"root": root}
    if target_python:
        parser["target"] = {"python": target_python}
    with open(ini_path, "w", encoding="utf-8") as f:
        parser.write(f)
    return ini_path
