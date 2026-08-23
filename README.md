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

- [x] 管理者モードからのマニフェスト編集UI（[実装済み](#マニフェスト編集管理者モード)。手動でのJSON編集は不要になった）
- [x] タスクスケジューラ連携による定期自己診断・自動レポート送信（[実装済み](#定期自己診断タスクスケジューラ連携)）
- [x] 共有サーバのアクセス権設定（config/python/wheelsは読取専用、statusは自ホスト名のみ書込可）用のスクリプトを用意
      （[実装済み](#共有サーバのアクセス権設定)。実際のAD/グループ名を渡してWindows実機・実サーバで実行するのはIT側の作業）
- [ ] 実際の組織標準ライブラリ（requests / numpy / pandas 等）用に `sample_runtime/config/manifest.json`
  と `sample_runtime/wheels/` を差し替え、UNC共有サーバの実パスに合わせて `DEFAULT_RUNTIME_ROOT` を更新
  — 貴社の標準パッケージ一覧・実UNCパスが必要（未着手）
- [ ] `runtime/python/<version>/` に組織標準のPythonインストーラ（python.org公式インストーラ）を配置し、
  Windows実機で「Pythonをインストール」ボタンの動作を検証（このプロトタイプはロジックのみモックで検証済み）
  — Windows実機での検証が必要（未着手）
- [ ] exeの社内配布・コードサイニング証明書での署名 — 貴社のコード署名証明書が必要（未着手）

### マニフェスト編集（管理者モード）

管理者モード画面の「マニフェスト編集」ボタンから `runtime/config/manifest.json` を直接編集できる
（[app/ui/manifest_editor.py](app/ui/manifest_editor.py)）。手動でのJSON編集は不要。

- 基本設定: Pythonバージョン／インストーラ相対パス／wheelhouseディレクトリ名
- パッケージ一覧: 組織標準ライブラリのマスタ（名前・バージョン）を行単位で追加・編集・削除
- グループ: 配布グループ（`default` 等）ごとの `extends` と参照パッケージを編集

保存時に整合性チェック（未定義パッケージの参照・`extends` の循環参照・`default` グループの存在など、
[app/manifest.py](app/manifest.py) の `validate_raw_manifest`）を行い、問題があれば保存を拒否する。
保存に成功すると `updated_at` が自動更新される。

### 定期自己診断（タスクスケジューラ連携）

GUIを開かずにスキャン・レポート送信（必要なら自動同期）だけを行うヘッドレスモードを追加した
（[app/cli.py](app/cli.py)）。

```powershell
# 開発時（ソースから直接）
python -m app.main check          # スキャンしてレポート送信のみ
python -m app.main check --sync   # 差分があれば自動同期まで実行

# ビルド済みexe（Windows実機）
PyEnvPanel.exe check
PyEnvPanel.exe check --sync
```

Pythonバージョン自体の不一致（サイレントインストールが必要なケース）は無人実行では自動化せず、
「要対応」として `runtime/status/<hostname>.json` に記録するのみに留める
（利用者の同意なくPython本体を差し替えないため）。

`pyenv_panel.spec` は `console=False` でビルドしているためタスクスケジューラ実行時は標準出力が見えない。
そのため実行結果は `runtime/logs/check_<hostname>.log` にも必ず出力する（開発時のターミナル実行では
標準出力にも表示される）。

タスクスケジューラへの登録は [packaging/register_scheduled_task.ps1](packaging/register_scheduled_task.ps1)
を使う（Windows実機で実行）。

```powershell
# 4時間ごとに自己診断＋自動同期を、ログオン中のみ実行するタスクを登録
.\packaging\register_scheduled_task.ps1 -ExePath "C:\Program Files\PyEnvPanel\PyEnvPanel.exe" -Sync

# 登録解除
.\packaging\register_scheduled_task.ps1 -Unregister
```

### 共有サーバのアクセス権設定

[packaging/setup_runtime_acl.ps1](packaging/setup_runtime_acl.ps1) は、共有ランタイムのルートに対して
設計書どおりのNTFSアクセス権（`config/` `python/` `wheels/` は読取専用、`status/` `logs/` は
自ホストが作成したファイルのみ変更可）を設定する（Windowsのファイルサーバ実機で、対象パスへの
アクセス権を持つアカウントで実行する）。

```powershell
.\packaging\setup_runtime_acl.ps1 -RuntimeRoot "\\fileserver\share\runtime" `
    -ReadOnlyGroup "CONTOSO\PyEnvPanel-Clients" -AdminGroup "CONTOSO\PyEnvPanel-Admins"
```

「自分が作成したレポートのみ変更できる（他端末のレポートは読めるが上書き・削除できない）」という
要件は、通常のグループ権限だけでは表現できないため、NTFSの `CREATOR OWNER` 特殊プリンシパルを用いて
実現している（スクリプト内コメント参照）。UNC共有の場合はSMB共有レベルの権限も別途必要になる点に注意。

## ディレクトリ構成

```
prototype/
├─ app/
│  ├─ config.py            共有ランタイムルート／対象Pythonの解決
│  ├─ models.py             データモデル
│  ├─ manifest.py           manifest.json の読み込み・編集UI向けの生JSON入出力／検証
│  ├─ scanner.py             対象Pythonのスキャンと差分計算
│  ├─ syncer.py              pip installによるオフライン同期
│  ├─ python_installer.py    Python本体のサイレントインストール
│  ├─ status.py              端末レポートの読み書き
│  ├─ service.py             GUI/CLI共通のサービス層
│  ├─ cli.py                 ヘッドレス自己診断（タスクスケジューラ向け、`app.main check`）
│  ├─ ui/
│  │  ├─ main_window.py      モード切替（QStackedWidget）
│  │  ├─ terminal_view.py    端末モード画面
│  │  ├─ admin_view.py       管理者モード画面
│  │  └─ manifest_editor.py  マニフェスト編集ダイアログ（管理者モードから起動）
│  └─ main.py                エントリポイント（GUI／`check`サブコマンドでヘッドレス実行を振り分け）
├─ run.py                    PyInstaller用エントリポイント（相対import対策）
├─ pyenv_panel.spec          PyInstallerビルド定義
├─ packaging/
│  ├─ app.ico                       アプリアイコン（プレースホルダ）
│  ├─ version_info.txt              Windowsバージョンリソース情報
│  ├─ register_scheduled_task.ps1   定期自己診断タスクの登録／解除
│  └─ setup_runtime_acl.ps1         共有ランタイムのNTFSアクセス権設定
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

### 追加実装分の動作確認（マニフェスト編集・タスクスケジューラ連携・ACLスクリプト）

- `app/manifest.py` の `load_raw_manifest` / `save_raw_manifest` / `validate_raw_manifest`:
  正常な読み込み・保存（`updated_at` 自動更新）、グループが未定義パッケージを参照するケース、
  `extends` の循環参照ケースをそれぞれ検証し、意図通りにエラー検出・保存拒否されることを確認
- `app/ui/manifest_editor.py` / `admin_view.py` / `main_window.py`:
  `QT_QPA_PLATFORM=offscreen` でダイアログ生成・パッケージ行追加・保存（ファイルへの反映）・
  管理者モードからの起動導線まで確認
- `app/cli.py`（`python -m app.cli check` / `check --sync`）:
  クリーンなテスト用venvに対して、未準拠→`--sync`による自動同期→再チェックで準拠状態になることと、
  終了コード（0/1/2）・`runtime/logs/check_<hostname>.log` へのログ出力を確認
- `packaging/register_scheduled_task.ps1` / `setup_runtime_acl.ps1`:
  このセッションはmacOS環境でPowerShellが無いため実行検証はできていない。内容のレビューで
  `Register-ScheduledTask` の `-Principal` と `-User`/`-Password` 併用不可（パラメータセット競合）の
  バグを検出・修正済み。実際の登録・ACL適用はWindows実機での確認が必要
