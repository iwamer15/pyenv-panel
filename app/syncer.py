"""共有ランタイムのホイールハウスを使ったオフライン同期処理。

pip install --no-index --find-links=<wheels> "name==version" の形で実行する。
インターネット非依存（--no-index）で、共有サーバ上に承認済みで置かれた
.whl ファイルのみからインストールする点がポイント。
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from .models import DiffItem, SyncResult


def sync_packages(
    target_python: str,
    wheels_dir: Path,
    diff_items: list[DiffItem],
    progress_cb: Callable[[str], None] | None = None,
    timeout: int = 120,
) -> list[SyncResult]:
    """必要なパッケージ（未インストール／バージョン不一致）のみをインストールする。"""
    results: list[SyncResult] = []
    targets = [d for d in diff_items if d.needs_action]

    if not wheels_dir.exists():
        for d in targets:
            results.append(SyncResult(d.name, d.required_version, False, f"ホイールハウスが見つかりません: {wheels_dir}"))
        return results

    for item in targets:
        spec = f"{item.name}=={item.required_version}"
        if progress_cb:
            progress_cb(f"インストール中: {spec}")
        try:
            proc = subprocess.run(
                [
                    target_python, "-m", "pip", "install",
                    "--no-index",
                    f"--find-links={wheels_dir}",
                    "--disable-pip-version-check",
                    spec,
                ],
                capture_output=True, text=True, timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as e:
            results.append(SyncResult(item.name, item.required_version, False, f"実行エラー: {e}"))
            continue

        if proc.returncode == 0:
            results.append(SyncResult(item.name, item.required_version, True, "インストール完了"))
        else:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            message = tail[-1] if tail else "不明なエラー"
            results.append(SyncResult(item.name, item.required_version, False, message))

    return results


def install_specs(
    target_python: str,
    specs: list[str],
    wheels_dir: Path | None,
    allow_online: bool,
    upgrade: bool = False,
    progress_cb: Callable[[str], None] | None = None,
    timeout: int = 600,
) -> list[SyncResult]:
    """ツール別画面からのインストール/更新。

    specs は "numpy>=1.24,<2" のような要件文字列。1件ずつ実行して結果を個別に返す。
    取得元:
      - 共有ホイールハウス（wheels_dir）が存在すれば常に --find-links で優先的に参照
      - allow_online=False のときは --no-index（社内承認済みの .whl のみ。オフライン）
      - allow_online=True のときは PyPI からも取得する
    upgrade=True は「要件の範囲内で最新へ更新」（pip install --upgrade）。
    """
    results: list[SyncResult] = []
    base_cmd = [target_python, "-m", "pip", "install", "--disable-pip-version-check"]
    if upgrade:
        base_cmd.append("--upgrade")
    if wheels_dir is not None and wheels_dir.exists():
        base_cmd.append(f"--find-links={wheels_dir}")
    elif not allow_online:
        for spec in specs:
            results.append(SyncResult(spec, "", False, f"オフライン指定ですがホイールハウスが見つかりません: {wheels_dir}"))
        return results
    if not allow_online:
        base_cmd.append("--no-index")

    for spec in specs:
        if progress_cb:
            progress_cb(f"{'更新' if upgrade else 'インストール'}中: {spec}")
        try:
            proc = subprocess.run(base_cmd + [spec], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as e:
            results.append(SyncResult(spec, "", False, f"実行エラー: {e}"))
            continue
        if proc.returncode == 0:
            lines = (proc.stdout or "").strip().splitlines()
            done = next((ln for ln in reversed(lines) if ln.startswith(("Successfully installed", "Requirement already satisfied"))), "完了")
            results.append(SyncResult(spec, "", True, done))
        else:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            results.append(SyncResult(spec, "", False, tail[-1] if tail else "不明なエラー"))
    return results


def build_python_install_hint(installer_path: Path) -> str:
    """Pythonバージョン自体の不一致時の案内文を組み立てる。

    プロトタイプではPython本体のサイレントインストールまでは自動実行しない
    （設計書 6章の運用・セキュリティ考慮を踏まえ、まずは検知と案内に留める。
     自動インストールはPhase2以降で実機検証の上、対応する）。
    """
    return (
        "対象Pythonのバージョンがマニフェストと異なります。\n"
        f"共有サーバのインストーラを使用してください:\n  {installer_path}\n"
        "（自動インストールは今後のフェーズで対応予定です）"
    )
