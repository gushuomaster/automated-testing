Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Get-RepositoryRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
}

function Get-MiniOrderArtifactsRoot {
    return Join-Path (Get-RepositoryRoot) 'artifacts\miniorder'
}

function Assert-PathWithinMiniOrderArtifacts {
    param([Parameter(Mandatory)][string]$Path)

    $root = [System.IO.Path]::GetFullPath((Get-MiniOrderArtifactsRoot))
    $resolved = [System.IO.Path]::GetFullPath($Path)
    $prefix = $root.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "路径不在 MiniOrder 产物目录内：$resolved"
    }
}

function Reset-GeneratedDirectory {
    param([Parameter(Mandatory)][string]$Path)

    Assert-PathWithinMiniOrderArtifacts -Path $Path
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（退出码 $LASTEXITCODE）：$FilePath $($Arguments -join ' ')"
    }
}
