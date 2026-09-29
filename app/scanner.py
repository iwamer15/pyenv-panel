"""ローカル環境（対象Python）のスキャンとマニフェストとの差分計算。

対象Python（target_python）は、このツール自身を動かしている Python とは
別物である前提とする（config.resolve_target_python 参照）。
そのため `python --version` / `pip list --format=json` をサブプロセスとして
実行し、対象インタプリタの実際の状態を取得する。
"""
from __future__ import annotations

import json
import re
import subprocess

from .manifest import ManifestData
from .models import DiffItem, DiffStatus

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


class ScanError(Exception):
    pass


def get_local_python_version(target_python: str, timeout: int = 15) -> str:
    try:
        proc = subprocess.run(
            [target_python, "--version"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ScanError(f"対象Python ({target_python}) を実行できませんでした: {e}") from e

    output = (proc.stdout or "") + (proc.stderr or "")  # Python 2系はstderrに出すため両方見る
    m = _VERSION_RE.search(output)
    if not m:
        raise ScanError(f"Pythonバージョンの取得に失敗しました。出力: {output!r}")
    return m.group(1)


def get_installed_packages(target_python: str, timeout: int = 30) -> dict[str, str]:
    """{パッケージ名(lower): バージョン} を返す。"""
    try:
        proc = subprocess.run(
            [target_python, "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ScanError(f"pip list の実行に失敗しました: {e}") from e

    if proc.returncode != 0:
        raise ScanError(f"pip list がエラー終了しました:\n{proc.stderr}")

    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ScanError(f"pip list の出力を解析できませんでした: {e}") from e

    return {item["name"].lower(): item["version"] for item in items}


# packaging.markers.default_environment() と同じキーを、対象Python側で計算させるスクリプト
# （このツール自身のPythonと対象Pythonはバージョン・OSが異なりうるため）。
_MARKER_ENV_SCRIPT = r"""
import json, os, platform, sys
def fmt(info):
    v = "%d.%d.%d" % (info.major, info.minor, info.micro)
    if info.releaselevel != "final":
        v += info.releaselevel[0] + str(info.serial)
    return v
print(json.dumps({
    "implementation_name": sys.implementation.name,
    "implementation_version": fmt(sys.implementation.version),
    "os_name": os.name,
    "platform_machine": platform.machine(),
    "platform_release": platform.release(),
    "platform_system": platform.system(),
    "platform_version": platform.version(),
    "python_full_version": platform.python_version(),
    "platform_python_implementation": platform.python_implementation(),
    "python_version": ".".join(platform.python_version_tuple()[:2]),
    "sys_platform": sys.platform,
}))
"""


def get_marker_environment(target_python: str, timeout: int = 15) -> dict[str, str] | None:
    """対象Pythonの環境マーカー値（sys_platform 等）を返す。取得できなければ None。"""
    try:
        proc = subprocess.run(
            [target_python, "-c", _MARKER_ENV_SCRIPT],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def compute_diff(manifest: ManifestData, installed: dict[str, str]) -> list[DiffItem]:
    diff_items: list[DiffItem] = []
    for req in manifest.packages:
        installed_version = installed.get(req.name.lower())
        if installed_version is None:
            status = DiffStatus.MISSING
        elif installed_version != req.version:
            status = DiffStatus.VERSION_MISMATCH
        else:
            status = DiffStatus.OK
        diff_items.append(
            DiffItem(
                name=req.name,
                required_version=req.version,
                installed_version=installed_version,
                status=status,
            )
        )
    return diff_items


def count_extra_packages(manifest: ManifestData, installed: dict[str, str]) -> int:
    required_names = {p.name.lower() for p in manifest.packages}
    return sum(1 for name in installed if name not in required_names)
