"""GUIを起動しないヘッドレス実行（タスクスケジューラでの定期自己診断・自動レポート送信用）。

README「実運用に向けて」の TODO の一つ:
    「タスクスケジューラ連携による定期自己診断・自動レポート送信」

に対応する。Windowsのタスクスケジューラ（またはPyInstallerでビルドしたexe）から

    PyEnvPanel.exe check
    PyEnvPanel.exe check --sync

のように呼び出す想定。`check` は対象Pythonをスキャンし、結果を必ず
runtime/status/<hostname>.json に書き込んで終了する（GUIは一切開かない）。
`--sync` を付けた場合、パッケージの差分（不足・不一致）があれば
`pip install --no-index --find-links` によるオフライン同期まで自動実行する。

Pythonバージョン自体の不一致（要 python.org インストーラでのサイレントインストール）は、
無人実行では自動化しない（利用者の同意なくPython本体を差し替えることは避ける設計）。
その場合は準拠状況を「要対応」としてレポートするだけに留め、終了コード1を返す。

ログについて:
    pyenv_panel.spec は console=False（コンソールを出さないGUIアプリ）でビルドしているため、
    タスクスケジューラから実行した場合 print() の出力先（コンソール）は存在しない。
    そのため実行結果は runtime/logs/check_<hostname>.log にも必ず書き込む
    （config.RuntimePaths.logs_dir）。標準出力が使える場合（開発時の `python -m app.main check` 等）は
    そちらにも出力する。

終了コード:
    0  準拠（compliant）、または --sync で同期し準拠状態になった
    1  未準拠（パッケージ差分が残っている、またはPythonバージョン不一致）
    2  スキャン自体が失敗した（マニフェスト読み込み不可・対象Python実行不可 等）
"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from . import service, status
from .config import RuntimePaths, resolve_runtime_root, resolve_target_python
from .manifest import ManifestError
from .scanner import ScanError

logger = logging.getLogger("pyenv_panel.cli")


def _setup_logging(paths: RuntimePaths) -> None:
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # console=False ビルドではコンソールが無く sys.stdout が None のことがあるため、
    # 使える場合のみ標準出力ハンドラを追加する（開発時のターミナル実行では見えるようにする）。
    if sys.stdout is not None:
        try:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(fmt)
            logger.addHandler(stream_handler)
        except (OSError, ValueError):
            pass

    try:
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            paths.logs_dir / f"check_{status.current_hostname()}.log",
            maxBytes=1_000_000, backupCount=3, encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as e:
        # ログファイルに書き込めなくても自己診断自体は継続する
        # （共有サーバに接続できない/読取専用等のケースを考慮）。
        if sys.stdout is not None:
            print(f"[WARN] ログファイルを書き込めませんでした: {e}", file=sys.stderr)


def run_check(group: str = "default", auto_sync: bool = False) -> int:
    paths = resolve_runtime_root()
    target_python = resolve_target_python()
    _setup_logging(paths)

    logger.info("runtime root  : %s", paths.root)
    logger.info("target python : %s", target_python)

    try:
        manifest, report = service.run_scan(paths, target_python, group=group)
    except (ManifestError, ScanError) as e:
        logger.error("スキャンに失敗しました: %s", e)
        return 2

    if report.compliant:
        status.write_status_report(paths.status_dir, report)
        logger.info("準拠しています（不足0・不一致0）。レポートを %s へ書き込みました。", paths.status_dir)
        return 0

    logger.warning(
        "未準拠です: Python=%s 不足=%d 不一致=%d",
        "OK" if report.python_compliant else "NG",
        report.missing_count, report.mismatch_count,
    )

    if not auto_sync:
        status.write_status_report(paths.status_dir, report)
        logger.info("--sync 未指定のため、自動同期は行わずレポートのみ書き込みました。")
        return 1

    if not report.python_compliant:
        status.write_status_report(paths.status_dir, report)
        logger.warning(
            "Pythonバージョン自体が不一致のため、無人実行では自動インストールしません"
            "（端末モードから手動で「Pythonをインストール」を実行してください）。"
        )
        return 1

    logger.info("パッケージ差分を自動同期します...")
    try:
        results, refreshed = service.run_sync_and_report(
            paths, target_python, manifest, report, progress_cb=logger.info,
        )
    except Exception as e:  # noqa: BLE001 - CLIとして状況をそのまま伝える
        logger.error("同期に失敗しました: %s", e)
        status.write_status_report(paths.status_dir, report)
        return 2

    for r in results:
        mark = "OK" if r.success else "NG"
        logger.info("  [%s] %s==%s: %s", mark, r.name, r.version, r.message)

    if refreshed.compliant:
        logger.info("同期完了・準拠状態になりました。")
        return 0

    logger.warning("同期後も未準拠です: 不足=%d 不一致=%d", refreshed.missing_count, refreshed.mismatch_count)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.cli",
        description="GUIを開かずにスキャン・自己診断レポート送信（同期）を行う。タスクスケジューラ用。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="スキャンして runtime/status/<hostname>.json を更新する")
    check_p.add_argument(
        "--group", default="default",
        help="マニフェストの配布グループ名（既定: default）",
    )
    check_p.add_argument(
        "--sync", action="store_true",
        help="パッケージ差分があれば --no-index --find-links によるオフライン同期まで自動実行する"
        "（Pythonバージョン自体の不一致は対象外）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "check":
        return run_check(group=args.group, auto_sync=args.sync)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
