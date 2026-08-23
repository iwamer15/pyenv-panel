# Python環境統一管理ツール（プロトタイプ）

設計書「Python環境統一管理ツール_設計書.docx」で定義したアーキテクチャの
プロトタイプです。PySide6で実装し、同一アプリ内で「端末モード」と
「管理者モード」を切り替えられます。

## できること

- 端末モード
  - `runtime/config/manifest.json`（共有サーバ上の「あるべき構成」）を読み込む
  - 対象Pythonのバージョン・インストール済みライブラリをスキャンし、マニフェストと差分表示
  - 「まとめて同期」で `pip install --no-index --find-links=<共有wheels>` を実行し、不足/不一致分を解消
  - Pythonバージョン自体が不一致の場合、「Pythonをインストール」ボタンで
    `runtime/python/<version>/` のインストーラをローカルにコピーし、サイレントインストール
    （`app/python_installer.py`。既存のPATH上のPythonには影響しない専用領域に導入）
  - 同期結果を `runtime/status/<hostname>.json` に書き出す
- 管理者モード
  - `runtime/status/` 配下の各端末レポートを集計し、組織全体の準拠率・端末別の状況を一覧表示

## セットアップ（開発・動作確認用）

```powershell
# Windows / PowerShell の例
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 実行方法

```powershell
python -m app.main
```

既定では、以下の優先順位で「共有ランタイムのルート」を解決します（`app/config.py`）。

1. 環境変数 `PYENV_PANEL_RUNTIME_ROOT`
2. `%APPDATA%\PyEnvPanel\config.ini` の `[runtime] root=...`
3. 本番既定値（`app/config.py` の `DEFAULT_RUNTIME_ROOT`、実際のUNCパスに書き換えて使用）
4. 開発用フォールバック: このリポジトリ同梱の `sample_runtime/`

対象Python（スキャン・同期・インストールの対象となるpython実行ファイル）は、環境変数
`PYENV_PANEL_TARGET_PYTHON` または `%APPDATA%\PyEnvPanel\config.ini` の
`[target] python=...` で指定できます。未指定時はPATH上の `python` を使用します。
Pythonインストール成功時は、このツールが自動的に `config.ini` の `[target] python` を
インストール先へ書き換えます。

### すぐ試す（同梱のサンプルデータで動かす場合）

```powershell
py -3.11 -m venv target_env
set PYENV_PANEL_TARGET_PYTHON=%CD%\target_env\Scripts\python.exe
python -m app.main
```

起動直後は `six` / `certifi` が未インストールの状態として表示されるはずなので、
「まとめて同期」を押すと `sample_runtime/wheels/` 内の `.whl` からオフラインインストールされ、
差分が解消されることを確認できます。

## exeビルド（Windows実機）

```powershell
.\build.ps1
```

`dist\PyEnvPanel.exe` が生成されます。中身は `pyenv_panel.spec`（PyInstaller定義）を参照してください。
アイコン（`packaging/app.ico`）とバージョンリソース（`packaging/version_info.txt`）はプレースホルダなので、
実運用時は組織のロゴ・製品名に差し替えてください。

macOS/LinuxではWindows向けexeは作れません（クロスビルド不可）。次章のGitHub Actionsを使うか、
Windows実機・VMで `build.ps1` を実行してください。

## GitHub Actionsでの自動ビルド・配布

`.github/workflows/build.yml` により、以下が自動化されています。

- `main` への push / PR / 手動実行: windows-latest ランナーでビルドが通ることを検証し、
  `PyEnvPanel-exe` という名前でビルド成果物をArtifactsに保存（動作確認用）
- `v*.*.*` 形式のタグをpushしたとき: 上記に加えてGitHub Releasesを自動作成し、
  `PyEnvPanel.exe` を添付する

```bash
git tag v0.1.0
git push origin v0.1.0
```

Windows端末側の利用者は、GitHubリポジトリの Releases ページ（最新版の固定リンクは
`https://github.com/<owner>/<repo>/releases/latest/download/PyEnvPanel.exe`）を開くだけで
exeをダウンロードできます。

## Claude Codeへの引き継ぎ手順（このプロトタイプをGitHubに公開する）

このzipを展開したフォルダで、ローカルのClaude Code（ターミナル版）を起動し、以下を依頼してください。

1. リポジトリ化とpush
   ```bash
   cd pyenv-panel   # 展開したフォルダ
   git init   # 既にgit化済みの場合は不要
   git add -A
   git commit -m "Initial prototype"
   gh repo create <組織 or 個人>/pyenv-panel --private --source=. --remote=origin --push
   ```
2. 動作確認: `python -m app.main` がローカルで起動すること、`sample_runtime/` を使ったデモが動くこと
3. タグを打ってGitHub Actionsのビルドを走らせる
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Actionsタブでビルド成功を確認し、Releasesページにexeが添付されていることを確認

その後、実運用に向けて以下をClaude Codeで進めるのがおすすめです（優先度順の目安）。

- 実際の組織標準ライブラリ（requests / numpy / pandas 等）用に `sample_runtime/config/manifest.json`
  と `sample_runtime/wheels/` を差し替え、UNC共有サーバの実パスに合わせて `DEFAULT_RUNTIME_ROOT` を更新
- `runtime/python/<version>/` に組織標準のPythonインストーラ（python.org公式インストーラ）を配置し、
  Windows実機で「Pythonをインストール」ボタンの動作を検証（このプロトタイプはロジックのみモックで検証済み）
- 管理者モードからのマニフェスト編集UI（現状は手動でJSON編集する想定）
- タスクスケジューラ連携による定期自己診断・自動レポート送信
- 共有サーバのアクセス権設定（config/python/wheelsは読取専用、statusは自ホスト名のみ書込可）
- exeの社内配布・コードサイニング証明書での署名

## ディレクトリ構成

```
prototype/
├─ app/
│  ├─ config.py            共有ランタイムルート／対象Pythonの解決
│  ├─ models.py             データモデル
│  ├─ manifest.py           manifest.json の読み込み
│  ├─ scanner.py             対象Pythonのスキャンと差分計算
│  ├─ syncer.py              pip installによるオフライン同期
│  ├─ python_installer.py    Python本体のサイレントインストール
│  ├─ status.py              端末レポートの読み書き
│  ├─ service.py             GUI/CLI共通のサービス層
│  ├─ ui/
│  │  ├─ main_window.py      モード切替（QStackedWidget）
│  │  ├─ terminal_view.py    端末モード画面
│  │  └─ admin_view.py       管理者モード画面
│  └─ main.py                エントリポイント
├─ run.py                    PyInstaller用エントリポイント（相対import対策）
├─ pyenv_panel.spec          PyInstallerビルド定義
├─ packaging/
│  ├─ app.ico                 アプリアイコン（プレースホルダ）
│  └─ version_info.txt        Windowsバージョンリソース情報
├─ build.ps1                  Windows実機用ビルドスクリプト
├─ .github/workflows/build.yml  GitHub Actionsビルド・リリース定義
├─ sample_runtime/            UNC共有サーバを模したサンプルデータ（開発・デモ用）
├─ requirements.txt
├─ requirements-dev.txt       requirements.txt + pyinstaller
└─ README.md
```

## 動作確認（このセッションで実施した検証）

- `python -m py_compile` による全モジュールの構文チェック
- `QT_QPA_PLATFORM=offscreen` でのGUI起動確認（端末モード・管理者モードともにウィンドウ生成、
  「Pythonをインストール」ボタンの表示切替まで確認）
- クリーンなテスト用venvを対象Pythonとして、
  スキャン→差分検出→`--no-index --find-links` によるオフライン同期→再スキャンで
  差分が解消されることをコマンドラインから確認
- `app/python_installer.py` の主要ロジック（インストーラ未検出時のエラー、サイレントインストール成功時の
  バージョン検証、既存インストール時のスキップ）を `subprocess.run` をモック化して検証
  （実際のWindowsインストーラ実行はWindows実機での確認が必要）
- `pyenv_panel.spec` を実際にPyInstallerでビルドし、生成物が起動することを確認
  （このセッションはLinux環境のためLinuxバイナリでの検証。Windows向けexeの生成自体は
  GitHub Actions（windows-latest）またはWindows実機で行う必要がある）
