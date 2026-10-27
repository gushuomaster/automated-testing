[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'Common.ps1')
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$executable = Join-Path (Get-MiniOrderArtifactsRoot) 'blackbox-run\MiniOrder.exe'
$dataDirectory = Join-Path (Get-MiniOrderArtifactsRoot) 'diagnostics\uia-workflow-data'
if (-not (Test-Path -LiteralPath $executable)) {
    throw "找不到 staged MiniOrder.exe：$executable"
}
Reset-GeneratedDirectory -Path $dataDirectory

function Start-MiniOrder {
    $process = Start-Process -FilePath $executable -ArgumentList @('--data-dir', $dataDirectory) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        Start-Sleep -Milliseconds 200
        $process.Refresh()
    } until ($process.MainWindowHandle -ne 0 -or $process.HasExited -or [DateTime]::UtcNow -ge $deadline)
    if ($process.HasExited -or $process.MainWindowHandle -eq 0) {
        throw 'MiniOrder 未在 10 秒内显示主窗口。'
    }
    return $process
}

function Find-ById {
    param($Root, [string]$Id)
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
        $Id)
    $element = $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
    if ($null -eq $element) { throw "未找到 UIA 控件：$Id" }
    return $element
}

function Set-UiValue {
    param($Root, [string]$Id, [string]$Value)
    $element = Find-ById -Root $Root -Id $Id
    $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($Value)
}

function Get-UiValue {
    param($Root, [string]$Id)
    $element = Find-ById -Root $Root -Id $Id
    return $element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value
}

function Invoke-UiControl {
    param($Root, [string]$Id)
    $element = Find-ById -Root $Root -Id $Id
    $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Start-Sleep -Milliseconds 250
}

function Select-UiTab {
    param($Root, [string]$Name)
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        $Name)
    $element = $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
    if ($null -eq $element) { throw "未找到页签：$Name" }
    $element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
    Start-Sleep -Milliseconds 250
}

function Assert-QueryCount {
    param($Root, [string]$Expected)
    $count = Find-ById -Root $Root -Id 'QueryResultCount'
    if ($count.Current.Name -ne $Expected) {
        throw "查询数量错误：期望 $Expected，实际 $($count.Current.Name)"
    }
}

function Close-MiniOrder {
    param($Process)
    [void]$Process.CloseMainWindow()
    if (-not $Process.WaitForExit(5000)) { throw 'MiniOrder 正常关闭超时。' }
}

$orderNumber = $null
$process = Start-MiniOrder
try {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    Set-UiValue $root 'CustomerNameInput' 'UIA 客户'
    Set-UiValue $root 'ProductNameInput' 'UIA 商品'
    Set-UiValue $root 'QuantityInput' '3'
    Set-UiValue $root 'UnitPriceInput' '12.50'
    Start-Sleep -Milliseconds 250
    $amount = Get-UiValue $root 'OrderAmountOutput'
    if ($amount -ne '37.50') { throw "金额错误：$amount" }

    Invoke-UiControl $root 'SaveOrderButton'
    $document = Get-Content -LiteralPath (Join-Path $dataDirectory 'orders.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($document.orders).Count -ne 1) { throw '有效保存后订单数不是 1。' }
    $orderNumber = $document.orders[0].orderNumber

    Set-UiValue $root 'CustomerNameInput' ''
    Set-UiValue $root 'ProductNameInput' '无效商品'
    Set-UiValue $root 'QuantityInput' '1'
    Set-UiValue $root 'UnitPriceInput' '1.00'
    Invoke-UiControl $root 'SaveOrderButton'
    $document = Get-Content -LiteralPath (Join-Path $dataDirectory 'orders.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($document.orders).Count -ne 1) { throw '无效保存改变了订单数。' }
    $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
    if ($focused.Current.AutomationId -ne 'CustomerNameInput') {
        throw "焦点未移到客户名称：$($focused.Current.AutomationId)"
    }

    Select-UiTab $root '查询订单'
    Set-UiValue $root 'QueryKeywordInput' 'UIA 客户'
    Invoke-UiControl $root 'QueryOrdersButton'
    Assert-QueryCount $root '找到 1 条订单'
    Write-Output "PASS 保存、无效拦截和查询；order=$orderNumber amount=$amount count=1"
    Write-Output 'LIMITATION WinForms DataGridView 未向当前 UIA provider 暴露单元格后代；行值留待视觉/CUA 复核。'
    Close-MiniOrder $process
}
finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

$process = Start-MiniOrder
try {
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($process.MainWindowHandle)
    Select-UiTab $root '查询订单'
    Set-UiValue $root 'QueryKeywordInput' 'UIA 客户'
    Invoke-UiControl $root 'QueryOrdersButton'
    Assert-QueryCount $root '找到 1 条订单'
    Write-Output "PASS 同目录重启后查询到 $orderNumber"
    Close-MiniOrder $process
}
finally {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}
