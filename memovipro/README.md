# MemoviPro

Evolución de **Memovi** orientada a automatizar tareas repetitivas en apps de
escritorio Windows con **iteración por DNI** desde Excel/CSV, **captura de
errores en ventanas emergentes** y **registro acumulado en Excel**.

A diferencia del Memovi original (coordenadas absolutas + eventos crudos),
MemoviPro trabaja con un **modelo de pasos simbólico** apoyado en
[pywinauto](https://pywinauto.readthedocs.io/) (UI Automation). Esto la hace
robusta frente a cambios de resolución, posición de ventana o tamaño de
botones.

## Características clave

- Modelo de pasos editable en YAML versionable (`macros/*.yaml`).
- Sustitución de placeholders en cualquier campo: `{DNI}`, `{YYYYMMDD}`,
  `{HHMMSS}`, `{NOMBRE}`, … (lo que haya en el Excel de DNIs).
- Iterador de DNIs con **checkpoint**: si la ejecución se interrumpe, al
  relanzar continúa solo con los pendientes.
- **Fingerprint de macro**: si modificas la macro, el checkpoint se invalida
  automáticamente para evitar marcar como completados DNIs con una versión
  obsoleta de los pasos.
- **Watchdog de popups** en hilo aparte: cualquier ventana emergente nueva
  durante la reproducción se detecta, se hace screenshot, se anota en Excel
  con el DNI culpable, y la reproducción pasa al siguiente DNI.
- **Excel acumulativo** `data/incidencias_YYYYMMDD.xlsx` con una fila por
  evento (OK o KO) e hipervínculo al PNG del popup.
- **Modo dry-run / simulación**: resalta los controles que se *clicarían* sin
  ejecutar acciones reales — ideal para depurar una macro nueva.
- **Reintento automático** de los DNIs KO al final del lote, con timeouts × 2
  (la mayoría de errores son transitorios).
- **Notificación por email** al terminar (SMTP) con resumen HTML + Excel de
  incidencias adjunto. Se configura en `config.json`.
- **Inspector de controles embebido**: clic en cualquier botón y MemoviPro
  rellena el `selector` (nombre/AutomationId/ClassName) del paso seleccionado.
- **Logs estructurados** en `logs/run_YYYYMMDD.log` con rotación diaria y
  retención de 30 días (loguru).
- **CLI sin GUI** (`cli.py`) con códigos de salida (0=OK, 2=KO parcial,
  1=error fatal) para invocar desde scripts o Task Scheduler.
- **Programación con Task Scheduler de Windows** desde la propia GUI:
  diaria, semanal o al iniciar sesión.
- **Empaquetado en `.exe`** con PyInstaller (`memovipro-run.exe` para CLI y
  `memovipro-gui.exe` para la GUI).
- **Wrapper PowerShell** (`RunMacro.ps1`) que captura excepciones y deja
  transcript diario.
- GUI PyQt6 con 4 pestañas: editor de macros, panel de ejecución,
  programación de tareas, visor de incidencias.
- Hotkey de pánico `Ctrl+Alt+Esc` para abortar instantáneamente.

## Estructura

```
memovipro/
├── app.py                # Punto de entrada de la GUI
├── config.json           # Parámetros globales
├── core/
│   ├── step_model.py     # Macro / Step / Selector + YAML
│   ├── recorder.py       # Grabador inteligente
│   ├── player.py         # Reproductor por pasos
│   ├── popup_watchdog.py # Vigilante de ventanas emergentes
│   ├── dni_iterator.py   # Lectura de Excel/CSV + checkpoint
│   ├── excel_logger.py   # Log acumulativo de incidencias
│   ├── screenshot.py     # Capturas (mss)
│   ├── libreoffice.py    # Manejador de "Guardar como" de LibreOffice
│   └── runner.py         # Orquestador
├── ui/
│   ├── main_window.py
│   ├── step_editor.py
│   ├── run_panel.py
│   └── incidents_view.py
├── macros/               # Macros YAML (versionables en git)
├── data/
│   ├── incidencias_YYYYMMDD.xlsx
│   ├── checkpoint_<macro>_YYYYMMDD.json
│   └── screenshots/
├── tools/
│   └── migrar_legacy.py  # Convierte JSON antiguos de Memovi a YAML
├── tests/                # 17 tests unitarios (no requieren Windows)
├── logs/                 # logs diarios con rotación
├── RepartoPA.ps1         # Script de distribución (con los fixes)
└── requirements.txt
```

## Instalación

```bash
pip install -r requirements.txt
```

> `pywinauto` solo se instala en Windows (gating en `requirements.txt`).
> En Linux/macOS puedes ejecutar la GUI y los tests, pero la reproducción
> real solo funciona en Windows.

## Uso

### 1. Diseñar una macro

```bash
python app.py
```

En la pestaña **Macros**: define el título de la ventana principal, añade los
pasos (focus_window, click_control, type_text, wait_until, …), edita los
valores con placeholders `{DNI}` y guarda como `macros/mi_macro.yaml`.

### 2. Preparar el Excel de DNIs

Una columna `DNI` (mayúsculas/minúsculas indiferente) y, opcionalmente,
otras columnas que pueden usarse como placeholders (`{NOMBRE}`, `{SERVICIO}`…).

### 3. Ejecutar

Pestaña **Ejecutar** → selecciona macro y Excel → "▶ Ejecutar".
La barra de progreso avanza por DNI; al terminar se abre la pestaña
**Incidencias** con el detalle.

### 4. Revisar incidencias

Pestaña **Incidencias**: tabla coloreada (verde = OK, rojo = KO). Doble clic
sobre la celda *Screenshot* abre la captura.

## Tests

```bash
python -m pytest tests/ -v
```

Los tests cubren step_model (YAML roundtrip y placeholders), excel_logger
(acumulación y agregados) y dni_iterator (lectura, normalización y
checkpoint). Todos pasan sin necesidad de Windows.

## Migrar grabaciones antiguas de Memovi

```bash
python tools/migrar_legacy.py ruta/legacy.json macros/migrada.yaml
```

Los clics se importan como `click_at_xy` (frágiles). **Revisión manual obligatoria**
para sustituirlos por `click_control` con selectores simbólicos antes de
usarlos en producción.

## Ejecución desatendida y programación

### Restricción importante

Como MemoviPro simula ratón y teclado, las tareas **necesitan una sesión
Windows iniciada** (no se pueden correr como servicio en background). Lo
recomendado es dejar el PC con tu usuario conectado y bloquear la sesión
si quieres.

### CLI

```cmd
python cli.py --macro descarga_it --excel D:\datos\dnis.xlsx
python cli.py --macro descarga_it --excel D:\datos\dnis.xlsx --dry-run
python cli.py --macro descarga_it --excel D:\datos\dnis.xlsx --all --no-notify
```

Códigos de salida: `0`=todo OK · `2`=terminó con DNIs KO · `1`=error fatal.

### Empaquetar como .exe

```cmd
pip install pyinstaller
pyinstaller memovipro-run.spec --clean   # → dist\memovipro-run.exe (sin GUI)
pyinstaller memovipro-gui.spec --clean   # → dist\memovipro-gui.exe (con GUI)
```

### Programar la ejecución

**Opción A — desde la GUI** (recomendada): pestaña **Programación** →
elige macro, Excel, frecuencia (diaria / semanal / al iniciar sesión) y
"Programar tarea". Se crean con prefijo `MemoviPro_` y se pueden
listar/eliminar desde la misma pestaña.

**Opción B — PowerShell + Task Scheduler manual**:

```powershell
# Crear tarea diaria a las 08:00
schtasks /Create /TN "MemoviPro_descarga_it" /SC DAILY /ST 08:00 /RL LIMITED /IT `
  /TR "powershell.exe -ExecutionPolicy Bypass -File C:\Apps\MemoviPro\RunMacro.ps1 -Macro descarga_it -Excel D:\datos\dnis.xlsx"
```

El script `RunMacro.ps1` deja transcript en `logs\powershell_YYYYMMDD.log` y
propaga el exit code del CLI.

### Resumen del flujo recomendado en producción

1. Diseñas la macro con la GUI (Inspector + dry-run para validar).
2. Empaquetas el ejecutable: `pyinstaller memovipro-run.spec --clean`.
3. Programas con la pestaña **Programación** apuntando al `.exe`.
4. Cada mañana revisas los emails de resumen y la pestaña **Incidencias**
   para los DNIs marcados en rojo (con su screenshot del popup).
