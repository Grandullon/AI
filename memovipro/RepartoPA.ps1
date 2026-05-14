# ==============================================================================
# BOT DE DISTRIBUCIÓN DE PA-DIARIO (PERSONAL ACTIVO)
# ==============================================================================
# 1) Detecta el archivo más reciente en la carpeta de origen PA-Auto.
# 2) Lo COPIA a las 4 carpetas de destino.
# 3) Si el archivo ya existe, lo SOBRESCRIBE (-Force).
# 4) Deja transcripción en logs\reparto_YYYYMMDD.log
# ==============================================================================

$ErrorActionPreference = 'Stop'

# --- LOGGING ---
$LogDir = Join-Path $PSScriptRoot 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("reparto_{0:yyyyMMdd}.log" -f (Get-Date))
Start-Transcript -Path $LogFile -Append | Out-Null

# --- CONFIGURACIÓN DE FECHAS ---
$FechaHoy = Get-Date
$Anio     = $FechaHoy.ToString("yyyy")

# --- FUNCIÓN DE COPIA INTELIGENTE ---
function Enviar-UltimoArchivo {
    param(
        [string]$Origen,
        [array]$Destinos,
        [string]$NombreProceso
    )

    Write-Host "`n========================================================" -ForegroundColor Cyan
    Write-Host " INICIANDO: $NombreProceso"
    Write-Host "========================================================"

    if (-not (Test-Path $Origen)) {
        Write-Warning " [!] La carpeta origen no existe: $Origen"
        return
    }

    $archivo = Get-ChildItem -Path $Origen -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $archivo) {
        Write-Warning " [!] No hay archivos para enviar en la carpeta origen."
        return
    }

    Write-Host " Archivo detectado: " -NoNewline
    Write-Host "$($archivo.Name)" -ForegroundColor Yellow
    Write-Host " (Modificado: $($archivo.LastWriteTime))"

    foreach ($destino in $Destinos) {
        if (-not (Test-Path $destino)) {
            try {
                New-Item -ItemType Directory -Path $destino -Force | Out-Null
                Write-Host " [INFO] Carpeta creada: $destino" -ForegroundColor Gray
            } catch {
                Write-Host " [ERROR] No se pudo crear la carpeta: $destino" -ForegroundColor Red
                continue
            }
        }

        $rutaDestinoCompleta = Join-Path -Path $destino -ChildPath $archivo.Name

        try {
            Copy-Item -Path $archivo.FullName -Destination $rutaDestinoCompleta -Force
            Write-Host " [OK] Enviado a -> $destino" -ForegroundColor Green
        }
        catch {
            Write-Host " [ERROR] Falló el envío a -> $destino" -ForegroundColor Red
            Write-Host " Detalle: $_"
        }
    }
}

# ==============================================================================
# BLOQUE: PA-DIARIO (PERSONAL ACTIVO)
# ==============================================================================

$origenPA = "\\Alhambra\grupo`$\GrupodeApoyoGestion\AUTO-PA\PA-Auto"

$destinosPA = @(
    "\\Alhambra\grupo`$\GrupodeApoyoGestion\H. VIRGEN NIEVES $Anio\TABLAS MAESTRAS\PA-Diario",
    "\\Alhambra\grupo`$\CapituloI\PERSONAL ACTIVO",
    "\\Alhambra\grupo`$\Seleccion_y_Provision\PERSONAL ACTIVO\PERSONAL ACTIVO DIARIO",
    "\\Alhambra\grupo`$\HUVN-PERSONAL-ACTIVO\Personal Activo\$Anio"
)

Enviar-UltimoArchivo -Origen $origenPA -Destinos $destinosPA -NombreProceso "PA-DIARIO"

Write-Host "`nPROCESO COMPLETADO. Pulsa Enter para salir."
Stop-Transcript | Out-Null
Read-Host
