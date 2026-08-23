"""runtime/config/manifest.json の読み込み。

マニフェストの形式は設計書 4.3 節を参照:

{
  "schema_version": 1,
  "updated_at": "...",
  "python": {"version": "3.11.9", "installer_path": "python/3.11.9/..."},
  "packages": [{"name": "requests", "version": "2.32.3"}, ...],
  "wheelhouse": "wheels",
  "groups": {
    "default": {"packages": ["requests", "numpy", "pandas"]},
    "data-science": {"extends": "default", "packages": ["scikit-learn"]}
  }
}
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import ManifestData, PackageRequirement


class ManifestError(Exception):
    pass


def _resolve_group_packages(raw: dict, group: str, _seen: set[str] | None = None) -> list[str]:
    groups = raw.get("groups", {})
    if group not in groups:
        raise ManifestError(f"マニフェストに存在しないグループです: {group}")
    _seen = _seen or set()
    if group in _seen:
        raise ManifestError(f"groups の extends が循環参照しています: {group}")
    _seen.add(group)

    g = groups[group]
    names: list[str] = []
    parent = g.get("extends")
    if parent:
        names.extend(_resolve_group_packages(raw, parent, _seen))
    for name in g.get("packages", []):
        if name not in names:
            names.append(name)
    return names


def load_manifest(manifest_path: Path, group: str = "default") -> ManifestData:
    if not manifest_path.exists():
        raise ManifestError(
            f"マニフェストが見つかりません: {manifest_path}\n"
            "共有サーバに接続できているか、runtime/config/manifest.json が存在するか確認してください。"
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"マニフェストのJSON解析に失敗しました: {e}") from e

    try:
        python_raw = raw["python"]
        all_packages_raw = raw["packages"]
    except KeyError as e:
        raise ManifestError(f"マニフェストに必須項目がありません: {e}") from e

    version_by_name = {p["name"]: p["version"] for p in all_packages_raw}

    group_package_names = _resolve_group_packages(raw, group)
    if not group_package_names:
        # groups が定義されていない/空の場合は packages 全体を使う
        group_package_names = list(version_by_name.keys())

    packages: list[PackageRequirement] = []
    for name in group_package_names:
        if name not in version_by_name:
            raise ManifestError(f"グループ '{group}' が参照するパッケージ '{name}' が packages に定義されていません")
        packages.append(PackageRequirement(name=name, version=version_by_name[name]))

    return ManifestData(
        schema_version=raw.get("schema_version", 1),
        updated_at=raw.get("updated_at", ""),
        python_version=python_raw.get("version", ""),
        python_installer_path=python_raw.get("installer_path", ""),
        packages=packages,
        wheelhouse_dir_name=raw.get("wheelhouse", "wheels"),
        group=group,
    )
