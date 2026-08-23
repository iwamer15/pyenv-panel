# Windows実機でexeをビルドするためのスクリプト。
# 実行例（PowerShell）:
#   .\build.ps1
#
# 前提: Python 3.11系がインストールされ、python コマンドがPATHに通っていること。

$ErrorActionPreference = "Stop"

Write-Host "==> venv作成"
if (-not (Test-Path ".build-venv")) {
    python -m venv .build-venv
}
. .\.build-venv\Scripts\Activate.ps1

Write-Host "==> 依存関係インストール"
python -m pip install --upgrade pip
pip install -r requirements-dev.txt

Write-Host "==> PyInstallerビルド"
pyinstaller pyenv_panel.spec --noconfirm --clean

Write-Host "==> 完了: dist\PyEnvPanel.exe"
Get-Item "dist\PyEnvPanel.exe" | Format-List Name, Length, LastWriteTime
