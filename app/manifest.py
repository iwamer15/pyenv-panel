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
from datetime import datetime, timezone
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


# --- 管理者モードのマニフェスト編集UI向け: 生JSONの読み書き -----------------
#
# load_manifest() はグループ解決済みの ManifestData（表示・スキャン用の読み取り専用ビュー）
# を返すが、編集UIは manifest.json 全体（packages マスタ・groups定義すべて）を
# 保持・書き戻す必要があるため、生の dict のまま扱う専用の入出力関数を用意する。

def load_raw_manifest(manifest_path: Path) -> dict:
    """manifest.json をそのまま dict として読み込む（編集UI用）。"""
    if not manifest_path.exists():
        raise ManifestError(f"マニフェストが見つかりません: {manifest_path}")
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ManifestError(f"マニフェストのJSON解析に失敗しました: {e}") from e


def validate_raw_manifest(raw: dict) -> list[str]:
    """保存前の整合性チェック。エラーメッセージの一覧を返す（空なら問題なし）。"""
    errors: list[str] = []

    python_raw = raw.get("python")
    if not isinstance(python_raw, dict) or not python_raw.get("version"):
        errors.append("Pythonバージョンが未入力です。")

    packages_raw = raw.get("packages")
    if not isinstance(packages_raw, list) or not packages_raw:
        errors.append("パッケージが1件も定義されていません。")
    else:
        seen_names: set[str] = set()
        for p in packages_raw:
            name = (p.get("name") or "").strip()
            version = (p.get("version") or "").strip()
            if not name:
                errors.append("パッケージ名が空の行があります。")
                continue
            if not version:
                errors.append(f"パッケージ '{name}' のバージョンが空です。")
            if name.lower() in seen_names:
                errors.append(f"パッケージ名 '{name}' が重複しています。")
            seen_names.add(name.lower())

    package_names = {(p.get("name") or "").strip().lower() for p in (packages_raw or [])}
    groups_raw = raw.get("groups", {})
    if not isinstance(groups_raw, dict) or not groups_raw:
        errors.append("groups が1件も定義されていません（少なくとも 'default' が必要です）。")
    elif "default" not in groups_raw:
        errors.append("groups に 'default' グループがありません。")
    else:
        for group_name, g in groups_raw.items():
            for pkg_name in g.get("packages", []):
                if pkg_name.strip().lower() not in package_names:
                    errors.append(
                        f"グループ '{group_name}' がパッケージ一覧に無い '{pkg_name}' を参照しています。"
                    )
            extends = g.get("extends")
            if extends and extends not in groups_raw:
                errors.append(f"グループ '{group_name}' の extends 先 '{extends}' が存在しません。")

        # 循環参照チェック（load_manifest と同じロジックを流用して各グループを解決してみる）
        for group_name in groups_raw:
            try:
                _resolve_group_packages(raw, group_name)
            except ManifestError as e:
                errors.append(str(e))

    return errors


def save_raw_manifest(manifest_path: Path, raw: dict) -> None:
    """生dictを検証のうえ manifest.json へ書き戻す（updated_at は自動更新）。"""
    errors = validate_raw_manifest(raw)
    if errors:
        raise ManifestError("マニフェストの内容に誤りがあります:\n- " + "\n- ".join(errors))

    raw = dict(raw)
    raw["updated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
