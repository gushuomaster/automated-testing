[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('baseline', 'variant-a', 'variant-b')]
    [string]$Variant
)

. (Join-Path $PSScriptRoot 'Common.ps1')

$repositoryRoot = Get-RepositoryRoot
$artifactsRoot = Get-MiniOrderArtifactsRoot
$source = Join-Path $artifactsRoot "distributions\$Variant\MiniOrder.exe"
$requirements = Join-Path $repositoryRoot 'docs\miniorder\MiniOrder-Requirements.md'
$target = Join-Path $artifactsRoot 'blackbox-run'

if (-not (Test-Path -LiteralPath $source)) {
    throw "找不到指定发行包，请先运行 Build-Distributions.ps1：$source"
}
if (-not (Test-Path -LiteralPath $requirements)) {
    throw "找不到需求文档：$requirements"
}

Reset-GeneratedDirectory -Path $target
Copy-Item -LiteralPath $source -Destination (Join-Path $target 'MiniOrder.exe')
Copy-Item -LiteralPath $requirements -Destination (Join-Path $target 'MiniOrder-Requirements.md')

$allowed = @('MiniOrder.exe', 'MiniOrder-Requirements.md')
$actual = @(Get-ChildItem -LiteralPath $target -File | Select-Object -ExpandProperty Name)
$directories = @(Get-ChildItem -LiteralPath $target -Directory)
$unexpected = @($actual | Where-Object { $_ -notin $allowed })
$missing = @($allowed | Where-Object { $_ -notin $actual })
if ($unexpected.Count -gt 0 -or $missing.Count -gt 0 -or $directories.Count -gt 0) {
    throw "黑盒目录 allowlist 验证失败。缺少：$($missing -join ', ')；多余：$($unexpected -join ', ')"
}

if ($actual | Where-Object { $_ -match '(?i)variant|baseline|defect|verification|\.pdb$|\.ps1$|\.cs$' }) {
    throw '黑盒目录包含泄露版本身份或实现信息的文件名。'
}

Write-Output "STAGED files=$($actual.Count) executableSha256=$((Get-FileHash -LiteralPath (Join-Path $target 'MiniOrder.exe') -Algorithm SHA256).Hash)"
