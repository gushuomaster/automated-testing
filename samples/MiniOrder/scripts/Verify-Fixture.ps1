[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'Common.ps1')

$repositoryRoot = Get-RepositoryRoot
$solution = Join-Path $repositoryRoot 'samples\MiniOrder\MiniOrder.slnx'
$verification = Join-Path $repositoryRoot 'samples\MiniOrder\src\MiniOrder.Verification\MiniOrder.Verification.csproj'
$seed = Join-Path $repositoryRoot 'samples\MiniOrder\evaluation\seed\orders.json'
$diagnostics = Join-Path (Get-MiniOrderArtifactsRoot) 'diagnostics'
$resetDirectory = Join-Path $diagnostics 'verification\reset-final'
$log = Join-Path $diagnostics 'verification.log'

New-Item -ItemType Directory -Path $diagnostics -Force | Out-Null
$lines = [System.Collections.Generic.List[string]]::new()
function Record-Line([string]$Text) {
    $lines.Add($Text)
    Write-Output $Text
}

foreach ($variant in @('Baseline', 'VariantA', 'VariantB')) {
    Invoke-Checked -FilePath 'dotnet' -Arguments @('restore', $solution, "-p:MiniOrderVariant=$variant")
    Invoke-Checked -FilePath 'dotnet' -Arguments @('build', $solution, '--configuration', 'Release', '--no-restore', "-p:MiniOrderVariant=$variant")
    $matrixOutput = & dotnet run --project $verification --configuration Release --no-build "-p:MiniOrderVariant=$variant" -- matrix 2>&1
    if ($LASTEXITCODE -ne 0) { throw "变体契约矩阵失败：$variant`n$($matrixOutput -join [Environment]::NewLine)" }
    foreach ($line in $matrixOutput) { Record-Line "[$variant] $line" }
}

$coreOutput = & dotnet run --project $verification --configuration Release --no-build '-p:MiniOrderVariant=Baseline' -- core 2>&1
if ($LASTEXITCODE -ne 0) { throw "完整核心契约失败。`n$($coreOutput -join [Environment]::NewLine)" }
foreach ($line in $coreOutput) { Record-Line "[core] $line" }

$acceptButtonDirectory = Join-Path $diagnostics 'verification\accept-button'
$acceptButtonOutput = & dotnet run --project $verification --configuration Release --no-build '-p:MiniOrderVariant=Baseline' -- accept-button $acceptButtonDirectory 2>&1
if ($LASTEXITCODE -ne 0) { throw "默认按钮验证失败。`n$($acceptButtonOutput -join [Environment]::NewLine)" }
foreach ($line in $acceptButtonOutput) { Record-Line "[accept-button] $line" }

$persistenceOutput = & dotnet run --project $verification --configuration Release --no-build '-p:MiniOrderVariant=Baseline' -- persistence 2>&1
if ($LASTEXITCODE -ne 0) { throw "持久化验证失败。`n$($persistenceOutput -join [Environment]::NewLine)" }
foreach ($line in $persistenceOutput) { Record-Line "[persistence] $line" }

$resetOutput = & dotnet run --project $verification --configuration Release --no-build '-p:MiniOrderVariant=Baseline' -- reset-check $seed $resetDirectory 2>&1
if ($LASTEXITCODE -ne 0) { throw "重置验证失败。`n$($resetOutput -join [Environment]::NewLine)" }
foreach ($line in $resetOutput) { Record-Line "[reset] $line" }

& (Join-Path $PSScriptRoot 'Build-Distributions.ps1') 2>&1 | ForEach-Object { Record-Line "[publish] $_" }
& (Join-Path $PSScriptRoot 'Stage-BlackBox.ps1') -Variant baseline 2>&1 | ForEach-Object { Record-Line "[stage] $_" }

[System.IO.File]::WriteAllLines($log, $lines, [System.Text.UTF8Encoding]::new($false))
Write-Output "PASS 完整非 GUI 验证；日志：$log"
