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
- **Watchdog de popups** en hilo aparte: cualquier ventana emergente nueva
  durante la reproducción se detecta, se hace screenshot, se anota en Excel
  con el DNI culpable, y la reproducción pasa al siguiente DNI.
- **Excel acumulativo** `data/incidencias_YYYYMMDD.xlsx` con una fila por
  evento (OK o KO) e hipervínculo al PNG del popup.
- GUI PyQt6 con 3 pestañas: editor de macros, panel de ejecución, visor de
  incidencias.
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
├── tests/                # 10 tests unitarios (no requieren Windows)
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
