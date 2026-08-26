# Compilar a un único .exe

En un equipo con Windows y Python 3.11+:

```bat
pip install pyinstaller

pyinstaller --onefile --windowed ^
  --name DashboardIT ^
  --add-data "plantilla_it.html;." ^
  actualizar_dashboard_it.py
```

El ejecutable queda en `dist\DashboardIT.exe`. La plantilla viaja dentro; el
programa la localiza con `sys._MEIPASS`.

Al lado del `.exe` conviene dejar `config_it.json` (se crea solo la primera vez
que se ejecuta). El `historial_it.json` se genera junto al HTML de salida.

## Tarea programada (recomendado)

Para que el informe esté hecho antes de que llegue nadie:

```bat
schtasks /create /tn "Dashboard IT HUVN" /tr "\"C:\Ruta\DashboardIT.exe\" --headless" ^
  /sc weekly /d LUN,MAR,MIE,JUE,VIE /st 09:15 /rl LIMITED
```

La tarea debe correr con una cuenta que tenga acceso de lectura a las carpetas
de volcados y de escritura en la carpeta de salida.

## Comprobación rápida antes de repartirlo

```bat
DashboardIT.exe --demo          :: datos inventados, valida que todo pinta bien
DashboardIT.exe --headless      :: datos reales, sin ventana
```

Si no encuentra volcados, el error dice exactamente en qué carpeta ha mirado y
qué patrón de nombre esperaba.
