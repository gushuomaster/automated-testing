[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'Common.ps1')
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$artifactsRoot = Get-MiniOrderArtifactsRoot
$variants = @('baseline', 'variant-a', 'variant-b')
$snapshots = @{}
$metadata = @{}
$hashes = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)

foreach ($variant in $variants) {
    $executable = Join-Path $artifactsRoot "distributions\$variant\MiniOrder.exe"
    $dataDirectory = Join-Path $artifactsRoot "diagnostics\identity-$variant"
    Reset-GeneratedDirectory -Path $dataDirectory
    $version = (Get-Item -LiteralPath $executable).VersionInfo
    $metadata[$variant] = "$($version.ProductName)|$($version.FileDescription)|$($version.ProductVersion)|$($version.FileVersion)"
    [void]$hashes.Add((Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash)

    $process = Start-Process -FilePath $executable -ArgumentList @('--data-dir', $dataDirectory) -PassThru
    try {
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        do { Start-Sleep -Milliseconds 200; $process.Refresh() }
        until ($process.MainWindowHandle -ne 0 -or $process.HasExited -or [DateTime]::UtcNow -ge $deadline)
        if ($process.MainWindowHandle -eq 0) { throw "$variant 未显示主窗口。" }
        $root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
        $lines = [System.Collections.Generic.List[string]]::new()

        foreach ($pageName in @('新建订单', '查询订单')) {
            $condition = [System.Windows.Automation.AndCondition]::new(
                [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::NameProperty,
                    $pageName),
                [System.Windows.Automation.PropertyCondition]::new(
                    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                    [System.Windows.Automation.ControlType]::TabItem))
            $tab = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
            $tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
            Start-Sleep -Milliseconds 200
            $elements = $root.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            for ($index = 0; $index -lt $elements.Count; $index++) {
                $element = $elements.Item($index)
                $lines.Add("$pageName|$($element.Current.ControlType.ProgrammaticName)|$($element.Current.AutomationId)|$($element.Current.Name)")
            }
        }
        $snapshots[$variant] = ($lines | Sort-Object -Unique) -join "`n"
        [void]$process.CloseMainWindow()
        if (-not $process.WaitForExit(5000)) { throw "$variant 关闭超时。" }
    }
    finally {
        if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
    }
}

if ($hashes.Count -ne $variants.Count) { throw '三个发行包的二进制 SHA-256 并非全部不同。' }
if (@($metadata.Values | Sort-Object -Unique).Count -ne 1) { throw '三个发行包的可见文件元数据不一致。' }
if (@($snapshots.Values | Sort-Object -Unique).Count -ne 1) { throw '三个发行包的 UIA 树不一致。' }

$log = Join-Path $artifactsRoot 'diagnostics\identity-comparison.txt'
$report = @(
    "metadata=$($metadata['baseline'])",
    "uniqueExecutableHashes=$($hashes.Count)",
    'uiaTreesIdentical=true',
    $snapshots['baseline']
)
[System.IO.File]::WriteAllLines($log, $report, [System.Text.UTF8Encoding]::new($false))
Write-Output "PASS 三个发行包元数据与 UIA 树一致，EXE 哈希各不相同；日志：$log"
