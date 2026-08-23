#Requires -Version 5.1
<#
.SYNOPSIS
    PyEnvPanel の定期自己診断（ヘッドレスチェック）をWindowsタスクスケジューラに登録/解除する。

.DESCRIPTION
    README「実運用に向けて」のTODO「タスクスケジューラ連携による定期自己診断・自動レポート送信」に対応する。

    登録したタスクは `PyEnvPanel.exe check`（または -Sync 指定時は `check --sync`）を
    定期実行する。GUIウィンドウは一切開かず、結果は runtime/status/<hostname>.json と
    runtime/logs/check_<hostname>.log に書き込まれる（app/cli.py 参照）。

    既定では「現在ログオン中のユーザー」として、ログオン中のみ実行するタスクを登録する。
    これは対象Pythonの解決（config.ini の [target] python=...）や共有サーバへのアクセス権が
    ユーザーごとに異なることが多いため、最もトラブルの少ない設定として採用している。
    ログオフ中も実行したい場合は -RunWhenLoggedOff を指定すること（実行時にパスワード入力を
    求められる。パスワードはタスクスケジューラがWindows資格情報マネージャーに保存するのみで、
    本スクリプトやPyEnvPanel自体が保持することはない）。

.PARAMETER ExePath
    PyEnvPanel.exe の配置先フルパス（例: C:\Program Files\PyEnvPanel\PyEnvPanel.exe）。

.PARAMETER TaskName
    タスクスケジューラ上のタスク名（既定: "PyEnvPanel Self-Check"）。

.PARAMETER IntervalHours
    自己診断の実行間隔（時間）。既定は4時間ごと。

.PARAMETER Sync
    差分があれば自動でオフライン同期（`check --sync`）まで行う。未指定時はスキャン＆レポート送信のみ。

.PARAMETER RunWhenLoggedOff
    ログオフ中・ロック中でも実行する（要パスワード入力・PowerShellの資格情報プロンプトが出る）。

.PARAMETER Unregister
    指定した場合、登録ではなくタスクの削除を行う。

.EXAMPLE
    # 4時間ごとに自己診断のみ（同期はしない）を、ログオン中のみ実行するタスクを登録
    .\register_scheduled_task.ps1 -ExePath "C:\Program Files\PyEnvPanel\PyEnvPanel.exe"

.EXAMPLE
    # 2時間ごとに自己診断＋自動同期。ログオフ中も実行（パスワード入力あり）
    .\register_scheduled_task.ps1 -ExePath "C:\Program Files\PyEnvPanel\PyEnvPanel.exe" `
        -IntervalHours 2 -Sync -RunWhenLoggedOff

.EXAMPLE
    # 登録済みタスクを削除
    .\register_scheduled_task.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string]$ExePath,
    [string]$TaskName = "PyEnvPanel Self-Check",
    [int]$IntervalHours = 4,
    [switch]$Sync,
    [switch]$RunWhenLoggedOff,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

if ($Unregister) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "タスク '$TaskName' は登録されていません。何もしません。"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "タスク '$TaskName' を削除しました。"
    exit 0
}

if (-not $ExePath) {
    throw "-ExePath を指定してください（例: -ExePath 'C:\Program Files\PyEnvPanel\PyEnvPanel.exe'）。削除する場合は -Unregister を指定してください。"
}
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "ExePath が見つかりません: $ExePath"
}

$taskArgs = "check"
if ($Sync) { $taskArgs += " --sync" }

$action = New-ScheduledTaskAction -Execute $ExePath -Argument $taskArgs

# 端末起動直後の1回に加え、以降 IntervalHours おきに実行し続けるトリガー。
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

if ($RunWhenLoggedOff) {
    # 注意: Register-ScheduledTask は -Principal と -User/-Password を同時に指定できない
    # （パラメータセットが競合しエラーになる）。-User/-Password/-RunLevel を直接渡すと
    # LogonType は自動的に Password（ログオフ中も実行可）として登録される。
    $cred = Get-Credential -Message "タスク実行アカウントの資格情報を入力してください（例: $env:USERDOMAIN\$env:USERNAME）"
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -User $cred.UserName -Password $cred.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null
} else {
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force | Out-Null
}

Write-Host "タスク '$TaskName' を登録しました（$IntervalHours 時間ごと、Sync=$($Sync.IsPresent)、RunWhenLoggedOff=$($RunWhenLoggedOff.IsPresent)）。"
Write-Host "動作確認: Start-ScheduledTask -TaskName '$TaskName' の後、runtime\logs\check_$($env:COMPUTERNAME).log を確認してください。"
