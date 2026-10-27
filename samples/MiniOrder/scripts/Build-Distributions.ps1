[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'Common.ps1')

$repositoryRoot = Get-RepositoryRoot
$project = Join-Path $repositoryRoot 'samples\MiniOrder\src\MiniOrder.App\MiniOrder.App.csproj'
$distributionRoot = Join-Path (Get-MiniOrderArtifactsRoot) 'distributions'
$variants = @(
    @{ Build = 'Baseline'; Folder = 'baseline' },
    @{ Build = 'VariantA'; Folder = 'variant-a' },
    @{ Build = 'VariantB'; Folder = 'variant-b' }
)

New-Item -ItemType Directory -Path $distributionRoot -Force | Out-Null
foreach ($variant in $variants) {
    $output = Join-Path $distributionRoot $variant.Folder
    Reset-GeneratedDirectory -Path $output
    Invoke-Checked -FilePath 'dotnet' -Arguments @(
        'restore', $project,
        '--runtime', 'win-x64',
        "-p:MiniOrderVariant=$($variant.Build)"
    )
    Invoke-Checked -FilePath 'dotnet' -Arguments @(
        'publish', $project,
        '--configuration', 'Release',
        '--no-restore',
        '--self-contained', 'false',
        '--runtime', 'win-x64',
        '--output', $output,
        "-p:MiniOrderVariant=$($variant.Build)",
        '-p:MiniOrderVariantExplicit=true',
        '-p:IsPublishing=true',
        '-p:PublishSingleFile=true',
        '-p:DebugSymbols=false',
        '-p:DebugType=None'
    )

    $executable = Join-Path $output 'MiniOrder.exe'
    if (-not (Test-Path -LiteralPath $executable)) {
        throw "发行包缺少 MiniOrder.exe：$output"
    }
    Write-Output "$($variant.Build) SHA256=$((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash)"
}
