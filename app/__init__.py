"""Python環境統一管理ツール - プロトタイプ実装。

このパッケージは設計書（Python環境統一管理ツール_設計書.docx）の
「4. システム全体アーキテクチャ」を最小構成で動かすためのプロトタイプです。

構成:
  config.py   共有ランタイムルート（runtime/）の解決
  models.py   データモデル（Manifest / DiffItem / StatusReport 等）
  manifest.py runtime/config/manifest.json の読み込み
  scanner.py  ローカル環境（Pythonバージョン・インストール済みパッケージ）のスキャンと差分計算
  syncer.py   pip install --no-index --find-links による同期処理
  status.py   runtime/status/<hostname>.json の読み書き（端末レポート）
  ui/         PySide6によるGUI（端末モード / 管理者モード）
  main.py     エントリポイント
"""

__version__ = "0.1.0"
