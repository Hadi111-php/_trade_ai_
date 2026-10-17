# run.ps1 — اجرا از ترمینال VS Code:
#   .\run.ps1                 -> داده زنده + موتور ریسک (PAPER)
#   .\run.ps1 -Offline        -> داده مصنوعی (بدون اینترنت)
#   .\run.ps1 -NoTrade        -> فقط سیگنال، بدون موتور ریسک
param(
    [switch]$Offline,
    [switch]$NoTrade
)
Set-Location $PSScriptRoot

$py = $null
foreach ($c in @("py", "python", "python3")) {
    if (Get-Command $c -ErrorAction SilentlyContinue) { $py = $c; break }
}
if (-not $py) {
    Write-Host "[ERROR] Python peida nashod. Python 3.9+ ba 'Add to PATH' nasb kon." -ForegroundColor Red
    exit 1
}
function RunPy([string[]]$a) {
    if ($script:py -eq "py") { & py -3 @a } else { & $script:py @a }
}

# بررسی ماژول
RunPy @("-c", "import scalplab") 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] module scalplab peida nashod; in script bayad DAKHEL apps\futures-scalp-lab bashad." -ForegroundColor Red
    exit 1
}

Write-Host "============================================================"
Write-Host "  Futures Scalp Lab - AUTO  [PAPER only - NO real orders]"
Write-Host "  Python: $py   Offline=$Offline  Trade=$(-not $NoTrade)"
Write-Host "============================================================"

$autoArgs = @("-m", "scalplab", "auto")
if ($Offline) {
    $autoArgs += @("--data", "synthetic", "--max-ticks", "500", "--seed", "7")
} else {
    $autoArgs += @("--data", "binance", "--symbol", "BTCUSDT", "--tf", "1m", "--interval", "5", "--forever")
}
if (-not $NoTrade) {
    $autoArgs += @("--trade", "--size", "100", "--leverage", "3", "--max-concurrent", "4",
                   "--cb-losses", "2", "--stop-pct", "0.005", "--trail-pct", "0.003")
}
RunPy $autoArgs
Write-Host "Stopped. Press any key."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
