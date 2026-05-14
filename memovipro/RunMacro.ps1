# ==============================================================================
# WRAPPER POWERSHELL PARA EJECUTAR UNA MACRO DE MEMOVIPRO
# ==============================================================================
# Uso desde Task Scheduler:
#   powershell.exe -ExecutionPolicy Bypass -File RunMacro.ps1
#                  -Macro descarga_it -Excel "D:\datos\dnis.xlsx"
#
# Captura excepciones, deja transcript diario en logs\powershell_YYYYMMDD.log
# y devuelve el código de salida del CLI (0/2/1).
# ==============================================================================

param(
    [Parameter(Mandatory = $true)][string]$Macro,
    [Parameter(Mandatory = $true)][string]$Excel,
    [switch]$DryRun,
    [switch]$NoRetry,
    [switch]$NoNotify,
    [switch]$All,
    [string]$ExePath = "",
    [string]$PythonPath = "python"
)

$ErrorActionPreference = 'Continue'

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir  = Join-Path $RootDir 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Transcript = Join-Path $LogDir ("powershell_{0:yyyyMMdd}.log" -f (Get-Date))
Start-Transcript -Path $Transcript -Append | Out-Null

Write-Host "============================================================"
Write-Host (" MemoviPro · {0:yyyy-MM-dd HH:mm:ss}" -f (Get-Date))
Write-Host (" Macro: {0}" -f $Macro)
Write-Host (" Excel: {0}" -f $Excel)
Write-Host "============================================================"

$Args = @("--macro", $Macro, "--excel", $Excel)
if ($DryRun)  { $Args += "--dry-run" }
if ($NoRetry) { $Args += "--no-retry" }
if ($NoNotify) { $Args += "--no-notify" }
if ($All)     { $Args += "--all" }

try {
    if ($ExePath -and (Test-Path $ExePath)) {
        & $ExePath @Args
    }
    else {
        $cli = Join-Path $RootDir "cli.py"
        if (-not (Test-Path $cli)) {
            throw "No se encuentra cli.py en $RootDir"
        }
        & $PythonPath $cli @Args
    }
    $code = $LASTEXITCODE
}
catch {
    Write-Host "[ERROR] $_" -ForegroundColor Red
    $code = 1
}

Write-Host ""
switch ($code) {
    0 { Write-Host "[OK] Macro terminada sin incidencias." -ForegroundColor Green }
    2 { Write-Host "[PARCIAL] Macro terminada con DNIs KO. Revisa data\incidencias_*.xlsx" -ForegroundColor Yellow }
    default { Write-Host "[FALLO] Error fatal (exit=$code). Revisa logs\run_*.log" -ForegroundColor Red }
}

Stop-Transcript | Out-Null
exit $code
