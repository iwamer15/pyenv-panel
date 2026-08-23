#Requires -Version 5.1
<#
.SYNOPSIS
    共有ランタイム（runtime/）配下のNTFSアクセス権を、設計書の想定どおりに設定する。
    「config/python/wheelsは読取専用、statusは自ホスト名のみ書込可」（README参照）。

.DESCRIPTION
    - config/, python/, wheels/ （組織側が配布する「あるべき構成」一式）
        通常端末: 読み取り＋実行のみ
        管理者　: フルコントロール
    - status/, logs/ （各端末が自己診断結果を書き込む場所）
        通常端末: 既存ファイルは全て読み取れるが、新規ファイルの作成のみ可能
                  （＝自分のレポートは書けるが、他端末のレポートを上書き・削除できない）
        管理者　: フルコントロール

    「自分が作成したファイルのみ変更できる」という要件は、通常のグループ単位のNTFS権限だけでは
    表現できないため、NTFSの特殊プリンシパル "CREATOR OWNER" を使う。
    フォルダ自体には「新規ファイル作成(WD)」のみを許可し、実際の読み書き権限は
    CREATOR OWNER の継承専用(IO)エントリを通じて「作成した本人」にのみ変更権限が付与される。

    このスクリプトは対象パス（ローカルパスまたはUNCパス）に対して icacls を実行する。
    UNCパス（SMB共有）の場合、共有レベルの権限（Grant-SmbShareAccess等）は別途設定が必要
    （NTFS権限と共有権限は両方を満たす必要があり、より厳しい方が適用される）。

.PARAMETER RuntimeRoot
    共有ランタイムのルートパス。例: \\fileserver\share\runtime

.PARAMETER ReadOnlyGroup
    一般端末（利用者）が属するAD等のグループ。例: "CONTOSO\PyEnvPanel-Clients"
    ドメイン内の全PCアカウントで統一したい場合は "CONTOSO\Domain Computers" 等でもよい。

.PARAMETER AdminGroup
    マニフェスト更新・wheel配置・全レポート閲覧ができるIT管理者グループ。
    例: "CONTOSO\PyEnvPanel-Admins"

.EXAMPLE
    .\setup_runtime_acl.ps1 -RuntimeRoot "\\fileserver\share\runtime" `
        -ReadOnlyGroup "CONTOSO\PyEnvPanel-Clients" -AdminGroup "CONTOSO\PyEnvPanel-Admins"

.EXAMPLE
    # 実際には変更せず、実行内容だけ確認する
    .\setup_runtime_acl.ps1 -RuntimeRoot "D:\runtime" -ReadOnlyGroup "CONTOSO\Clients" `
        -AdminGroup "CONTOSO\Admins" -WhatIf -Verbose
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string]$RuntimeRoot,
    [Parameter(Mandatory)] [string]$ReadOnlyGroup,
    [Parameter(Mandatory)] [string]$AdminGroup
)

$ErrorActionPreference = "Stop"

function Invoke-Icacls {
    param([string[]]$IcaclsArgs)
    Write-Verbose "icacls $($IcaclsArgs -join ' ')"
    $output = & icacls @IcaclsArgs
    if ($LASTEXITCODE -ne 0) {
        throw "icacls が失敗しました（終了コード $LASTEXITCODE）: icacls $($IcaclsArgs -join ' ')`n$output"
    }
    $output | ForEach-Object { Write-Verbose $_ }
}

if (-not (Test-Path -LiteralPath $RuntimeRoot)) {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
}

# --- 読取専用ディレクトリ（config / python / wheels） ---------------------
$readOnlyDirs = @("config", "python", "wheels")
foreach ($name in $readOnlyDirs) {
    $dir = Join-Path $RuntimeRoot $name
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    if ($PSCmdlet.ShouldProcess($dir, "NTFS権限を読取専用構成にリセット")) {
        Invoke-Icacls @($dir, "/inheritance:r")
        Invoke-Icacls @($dir, "/grant:r", "SYSTEM:(OI)(CI)F")
        Invoke-Icacls @($dir, "/grant:r", "*S-1-5-32-544:(OI)(CI)F")   # BUILTIN\Administrators
        Invoke-Icacls @($dir, "/grant:r", "${AdminGroup}:(OI)(CI)F")
        Invoke-Icacls @($dir, "/grant:r", "${ReadOnlyGroup}:(OI)(CI)RX")
    }
}

# --- 各端末が書き込むディレクトリ（status / logs） -------------------------
$writeDirs = @("status", "logs")
foreach ($name in $writeDirs) {
    $dir = Join-Path $RuntimeRoot $name
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    if ($PSCmdlet.ShouldProcess($dir, "NTFS権限を「自ホストのみ書込可」構成にリセット")) {
        Invoke-Icacls @($dir, "/inheritance:r")
        Invoke-Icacls @($dir, "/grant:r", "SYSTEM:(OI)(CI)F")
        Invoke-Icacls @($dir, "/grant:r", "*S-1-5-32-544:(OI)(CI)F")
        Invoke-Icacls @($dir, "/grant:r", "${AdminGroup}:(OI)(CI)F")
        # 既存/将来の全レポートを、全端末が読み取れる（管理者モードの集計に必要）。
        # 同じトラスティに対して2つ目以降のACEを追加する際は /grant:r ではなく /grant を使うこと
        # （:r はそのトラスティの既存の明示的権限を "置き換える" ため、直前のACEが消えてしまう）。
        Invoke-Icacls @($dir, "/grant:r", "${ReadOnlyGroup}:(OI)(CI)RX")
        # フォルダ直下への新規ファイル作成のみ許可（(OI)(CI)を付けないため既存ファイル/サブフォルダへは継承されない）
        Invoke-Icacls @($dir, "/grant", "${ReadOnlyGroup}:(WD,AD)")
        # 新規作成されたファイルの所有者（＝作成した本人）にだけ変更権限が付与される
        Invoke-Icacls @($dir, "/grant:r", "CREATOR OWNER:(OI)(CI)(IO)(M)")
    }
}

Write-Host "アクセス権設定が完了しました: $RuntimeRoot"
Write-Host "  読取専用: config/, python/, wheels/  -> ${ReadOnlyGroup}=読取実行のみ, ${AdminGroup}=フルコントロール"
Write-Host "  書込専用: status/, logs/            -> ${ReadOnlyGroup}=新規作成のみ(他ホスト上書き不可), ${AdminGroup}=フルコントロール"
Write-Host ""
Write-Host "注意: ${RuntimeRoot} がSMB共有（UNCパス）の場合、共有レベルの権限も別途設定が必要です"
Write-Host "      （例: Grant-SmbShareAccess -Name <共有名> -AccountName '${ReadOnlyGroup}' -AccessRight Change）。"
Write-Host "      NTFS権限と共有権限は両方を満たす必要があり、より厳しい方が実効権限になります。"
