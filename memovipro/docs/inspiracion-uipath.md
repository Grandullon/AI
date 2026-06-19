# Inspiración UiPath → MemoviPro

Síntesis de 5 ejes de investigación sobre el manual de UiPath (Studio + REFramework + Computer Vision + Document Understanding + Workflow Analyzer) y traducción a cambios concretos en MemoviPro.

## Dónde estamos vs dónde está UiPath

Hoy MemoviPro ya tiene varios pilares que UiPath llama de otra forma pero hacen lo mismo:

| UiPath | MemoviPro hoy |
|---|---|
| Modern Unified Target (selector → fuzzy → imagen) | cascada `selector → win_rel → imagen → coords` |
| Anchor Base activity | parcial: el `idx` y el contenedor |
| Try/Catch + Retry Scope | `on_fail=stop\|continue\|skip_rest` por macro |
| Step-Through Debugger | ya implementado con ← / → / "hasta aquí" / "desde aquí" |
| Validation Station | sin equivalente — los popups OCR se loggean sin revisar |
| Object Repository | sin equivalente — cada macro guarda sus selectores |
| Workflow Analyzer | sin equivalente — no hay linter |
| REFramework (init/process/end) | sin equivalente — el `PipelineRunner` no separa fases |

Lo que sigue son **12 mejoras priorizadas** por ROI/esfuerzo para que MemoviPro evolucione hacia el modelo robusto de UiPath sin volverse enterprise.

---

## Tabla maestra priorizada

| # | Mejora | Origen UiPath | Esfuerzo | Impacto |
|---|---|---|---|---|
| 1 | OCR con `image_to_data` (bbox + confianza por palabra) | Digitize de Document Understanding | Bajo | Alto |
| 2 | Score de confianza expuesto en `matchTemplate` + umbral configurable | CV Click "single point selection fallback" | Bajo | Alto |
| 3 | Distinguir `BusinessError` vs `SystemError` en el log de incidencias | REFramework SetTransactionStatus | Bajo | Alto |
| 4 | Recorder multi-técnica por defecto (todos los métodos en cada captura) | Modern "Indicate Target" / Unified Target | Bajo-Medio | Alto |
| 5 | Adoptar convenciones de nombres (ST-NMG-001, ST-NMG-002, ST-MRD-002) | Workflow Analyzer rules | Trivial | Medio |
| 6 | Linter ligero para YAML de macros (lint propio inspirado en Analyzer) | Workflow Analyzer | Medio | Alto |
| 7 | `RetryScope(action, condition, n, interval)` formalizado por paso | Modern Retry Scope activity | Medio | Alto |
| 8 | Sub-macros invocables `INVOKE_MACRO` con args `in_/out_/io_` | Invoke Workflow File + Arguments | Medio | Alto |
| 9 | Selector con `anchors: list[Selector]` + posición relativa | Modern Anchor+Target | Medio | Alto |
| 10 | Mini Validation Station PyQt6 con semáforo de confianza | Validation Station / Action Center | Medio | Alto |
| 11 | Step-Through avanzado: breakpoints condicionales + tracepoints + Locals/Watch/Immediate | Studio Debug Panels | Medio | Alto |
| 12 | State machine en `PipelineRunner` (Init → NextItem → Process → Cleanup) | REFramework 4 estados | Medio-Alto | Alto |
| 13 | Slow Step graduado (1x→2x→3x→4x) + Highlight Elements overlay | Studio Slow Step + Highlight | Bajo | Alto |
| 14 | Profile Execution + Test Activity (un paso aislado) | Studio Profile + Test Activity | Medio | Medio |

---

## Detalle de cada mejora

### 1. OCR con `pytesseract.image_to_data` en vez de `image_to_string`

UiPath Document Understanding separa **Digitize** (extraer texto **con posición y confianza**) del resto del pipeline. La equivalencia directa en tu stack es cambiar la llamada de Tesseract:

```python
# Antes
text = pytesseract.image_to_string(img, lang="spa+eng")

# Después
data = pytesseract.image_to_data(img, lang="spa+eng", output_type=Output.DICT)
# data["text"][i], data["conf"][i], data["left"][i], data["top"][i], data["width"][i], data["height"][i]
tokens = [(t, c, (l, t_, w, h)) for t, c, l, t_, w, h
          in zip(data["text"], data["conf"], data["left"], data["top"], data["width"], data["height"])
          if t.strip() and int(c) >= 60]
```

Con esto puedes:
- Descartar texto basura (`conf < 60`).
- **Hacer click sobre la palabra detectada** (centro del bbox) — alternativa robusta a template matching para botones con texto.
- Pintar bounding boxes en el screenshot de incidencia para depurar visualmente.

Fuente: https://docs.uipath.com/activities/other/latest/document-understanding/digitize-document

---

### 2. Confianza expuesta en `matchTemplate` + umbral configurable

Tu `core/image_match.py` ya hace `cv2.matchTemplate(..., TM_CCOEFF_NORMED)` que **ya devuelve un score 0-1**. UiPath documenta que su CV "no es 100% precisa" y por eso ofrece "single point selection" como fallback manual. Aplicado a MemoviPro:

- Expón `MIN_MATCH_CONFIDENCE` (default 0.85) en `config.json`.
- Loggea por cada click de imagen: `(score, x, y, paso_idx)` en la columna `detalle` del Excel de incidencias.
- Si el score top está entre 0.70 y 0.85 (zona gris), levanta una incidencia "low_confidence" en el log sin bloquear la ejecución.

Fuente: https://docs.uipath.com/activities/other/latest/ui-automation/cv-scope

---

### 3. `BusinessError` vs `SystemError` en el modelo de incidencias

La regla más importante del REFramework: **errores de negocio NO se reintentan, errores de sistema SÍ.**

> "Si el problema lo causa la regla de negocio, retry dará el mismo resultado hasta que un humano intervenga; si lo causa un glitch técnico, el retry puede arreglar solo."
> — UiPath REFramework SetTransactionStatus.xaml ([github.com/UiPath/ReFrameWork](https://github.com/UiPath/ReFrameWork/blob/master/Framework/SetTransactionStatus.xaml))

En MemoviPro hoy todo es "fallo" o "OK". Propuesta:

```python
class MemoviError(Exception): ...
class MemoviBusinessError(MemoviError):
    """Ej: 'DNI no existe', 'el campo X obliga a uno de [A,B,C]'."""
class MemoviSystemError(MemoviError):
    """Ej: 'ventana no apareció en 5s', 'la app cerró sola'."""
```

- En el watchdog, si el popup matchea una regex de errores de negocio (configurable por macro: lista de patrones), levanta `MemoviBusinessError` → la transacción se marca KO **sin reintentar**.
- Si el popup es genérico/inesperado o se cae la ventana, `MemoviSystemError` → activa la cadena de retry.
- Añade una columna `tipo_error` (`business`/`system`/`none`) en el Excel.

---

### 4. Recorder multi-técnica por defecto

> "Indicate Target captura múltiples técnicas de targeting *de una sola pasada*: selector estricto, selector fuzzy, anchor sugerido e imagen — el usuario no elige uno; el motor las prueba en orden en runtime."
> — UiPath Advanced Descriptor Configuration ([docs.uipath.com](https://docs.uipath.com/activities/other/latest/ui-automation/advanced-descriptor-configuration))

Hoy tu recorder ya graba algo de esto, pero no todo simultáneamente. Cambio concreto: **en cada captura, siempre graba los 5**:

1. `selector_strict`: full selector con todos los atributos.
2. `selector_fuzzy`: el mismo selector **quitando** `idx`, `runtime_id`, `class_name` si no es único, etc.
3. `target_image`: PNG del control (bbox 60×40 alrededor).
4. `screen_thumb`: thumbnail del screenshot completo.
5. `win_rel`: fracción `(x/w, y/h)` relativa a la ventana padre.

El player en runtime los prueba en cascada (1→2→3→5), igual que hoy pero ahora **el usuario no decide** qué guardar al capturar.

---

### 5. Convenciones de nombres oficiales (esfuerzo trivial, alto valor)

UiPath tiene tres reglas del Workflow Analyzer que merece la pena adoptar:

- **ST-NMG-001 — Variables camelCase**: variables internas en `step.extra`, `ctx`, etc. usan `camelCase` (regex `^(dt_)?([A-Z]|[a-z])+([0-9])*$`).
- **ST-NMG-002 — Args con prefijo de dirección**: cuando añadas el `INVOKE_MACRO` (mejora #8), los argumentos deben llamarse `in_DefaultTimeout`, `out_TextResult`, `io_RetryNumber`.
- **ST-MRD-002 — Descripciones de paso no por defecto**: prohíbe descripciones tipo `"Nuevo click_at_xy"`. Al añadir un paso, sugiere `"Click en {label_más_cercano}"`.

Fuente: https://docs.uipath.com/studio/standalone/2024.10/user-guide/st-nmg-002

---

### 6. Linter ligero para YAML de macros

Hereda 5-6 reglas del Workflow Analyzer adaptadas:

| Regla | Origen | Detección |
|---|---|---|
| `MV-NMG-001` | ST-NMG-001 | nombres de macros y pasos siguen camelCase / verbo+nombre |
| `MV-DBP-021` | ST-DBP-021 (Hardcoded Timeout) | `paso.delay_before_s > 30` o `paso.timeout_s == default` |
| `MV-USG-009` | ST-USG-009 (Unused Variables) | placeholders `{X}` declarados pero no usados |
| `MV-REL-001` | UI-REL-001 (Large Idx) | selector usa `found_index > 2` → fragilidad |
| `MV-DBP-023` | ST-DBP-023 (Empty Workflow) | macro sin pasos o sub-macro sin contenido |
| `MV-MRD-002` | ST-MRD-002 (Activity Name Default) | paso con `descripcion` empezando por "Nuevo " |

Implementación: un módulo `core/analyzer.py` con `analyze_macro(macro) → list[Issue]` que se ejecuta:
- al cargar una macro en el editor (mostrar warnings en el panel),
- al guardar (bloquear si hay errores graves),
- antes de programar una tarea (no programes una macro fragil).

Tu **Dashboard** (que ya tienes) puede sumar el score de fragilidad calculado por el analyzer para ordenar macros por "salud".

Fuente: https://docs.uipath.com/studio/standalone/2023.10/user-guide/about-workflow-analyzer

---

### 7. `RetryScope` formalizado por paso

Hoy el retry vive a nivel de cadena (`on_fail=stop|continue|skip_rest`) y a nivel de iteración (`veces`). Falta un retry **por paso** con condición de éxito explícita.

Modelo del Modern Retry Scope:

```python
@dataclass
class RetryScope:
    n_intentos: int = 3
    intervalo_s: float = 2.0
    condicion: Callable[[], bool] | None = None  # boolean activity

def ejecutar_con_retry(self, paso, scope: RetryScope):
    for intento in range(1, scope.n_intentos + 1):
        try:
            self._ejecutar_paso(paso, idx)
            if scope.condicion is None or scope.condicion():
                return  # OK
        except MemoviSystemError:
            if intento == scope.n_intentos:
                raise
        time.sleep(scope.intervalo_s)
```

La `condicion` reutiliza el campo `verificar_ventana` que ya tienes. Quedaría declarativo en el YAML:

```yaml
- tipo: click_control
  selector: {name: "Guardar"}
  retry: {n_intentos: 3, intervalo_s: 2, verificar: "INFORME guardado"}
```

Fuente: https://docs.uipath.com/activities/other/latest/workflow/retry-scope

---

### 8. Sub-macros invocables con argumentos tipados

Hoy las cadenas invocan macros enteras, pero no pasan datos. Sin reutilización fina.

Modelo (de Variables/Arguments + Invoke Workflow File):

```yaml
# macros/sub_login.yaml
nombre: login_gerhonte
args:
  - {nombre: in_Usuario, tipo: str, requerido: true}
  - {nombre: in_Password, tipo: str, requerido: true, secreto: true}
  - {nombre: out_SessionOk, tipo: bool}
pasos: [...]
```

```yaml
# macros/proceso_diario.yaml
pasos:
  - tipo: invoke_macro
    valor: login_gerhonte
    args_in:
      in_Usuario: "{USUARIO}"
      in_Password: "{SECRET:gerhonte_password}"
    args_out:
      out_SessionOk: session_ok
  - tipo: if_ventana   # ya lo tienes
    ventana: session_ok  # el output anterior
    saltar_si_no: 5
```

Nuevo `StepType.INVOKE_MACRO`. El runner carga la sub-macro, abre un sub-contexto con los `in_*`, ejecuta, y captura los `out_*` al contexto padre. **Convención de nombres `in_/out_/io_` como UiPath**.

Fuente: https://docs.uipath.com/activities/other/latest/workflow/invoke-workflow-file

---

### 9. Selector con `anchors: list[Selector]`

> "Modern Anchor+Target: el anchor es otro elemento estable cercano y se añade *dentro del mismo descriptor*; si no se encuentra el anchor en runtime, falla todo el matching."
> — UiPath docs

Caso de uso GERHONTE: un campo de texto sin `auto_id`, con label "DNI:" al lado. Hoy capturas el campo por `idx` (frágil). Con anchor:

```python
@dataclass
class Selector:
    # campos actuales...
    anchors: list[Selector] = field(default_factory=list)
    anchor_position: str = "auto"  # "auto" | "left" | "right" | "top" | "bottom"
```

El player primero resuelve el anchor (label "DNI:"), luego busca el target **en la región cercana** al anchor según `anchor_position`. Mucho más estable que `idx`.

Fuente: https://docs.uipath.com/activities/other/latest/ui-automation/advanced-descriptor-configuration

---

### 10. Mini Validation Station en PyQt6

La pieza con más ROI tangible. Cuando OCR/CV/matching extrae datos con confianza dudosa, levanta un diálogo PyQt6:

- A la izquierda: screenshot del popup con bboxes pintados sobre cada campo dudoso.
- A la derecha: tabla `campo | valor extraído | conf% | aceptar/corregir`.
- Semáforo igual al de UiPath:
  - **< 50%** rojo (revisar obligatorio)
  - **50-85%** amarillo (revisar recomendado)
  - **86-99%** verde claro
  - **100%** verde
- Persistir correcciones en `data/validaciones.sqlite` para auditoría y para reentrenar regex.

Solo dispara cuando la confianza está por debajo del umbral configurado, así no rompe la automatización desatendida.

Fuente: https://docs.uipath.com/activities/other/latest/document-understanding/present-validation-station

---

### 11. Step-Through avanzado: breakpoints condicionales, tracepoints, paneles

Tu Step-Through ya tiene navegación con flechas, "▶ Hasta aquí" y "▶ Desde aquí". Lo que falta para igualar al Studio Debug:

**Breakpoint condicional + hit count + tracepoint** (F9 sobre la fila): menú con tres modos:
- Simple: pausa siempre al llegar.
- Condicional: input de expresión Python evaluada contra el contexto. `ctx["DNI"].startswith("5")` o `ctx.get("retry_count", 0) > 3`.
- Tracepoint: **loguea sin pausar** (variante poco conocida del Studio). Ideal para diagnosticar sin romper el flujo.

> "Setting a condition and/or hit count turns the simple breakpoint to a conditional one. The hit count specifies the number of times the condition must be met before the execution breaks."
> — UiPath Studio docs ([breakpoints-and-bookmarks-panel](https://docs.uipath.com/studio/standalone/2024.10/user-guide/the-breakpoints-and-bookmarks-panel))

**Importante**: los breakpoints **NO persisten en runtime** (Studio los separa de debug). MemoviPro debe almacenarlos en `debug_breakpoints` aparte del YAML productivo, así un breakpoint olvidado nunca bloquea una tarea programada.

**4 paneles del Studio**, todos como `QDockWidget` ocultables:

| Panel | Qué muestra | Cuándo |
|---|---|---|
| **Locals** | tabla del contexto actual (DNI, ITERACION, vars de sub-macros) | siempre durante pausa |
| **Watch** | expresiones definidas por el usuario, reevaluadas tras cada paso | añadidas con click-derecho desde Locals |
| **Immediate** | REPL Python para evaluar ad-hoc sobre el estado pausado | solo en pausa |
| **Call Stack** | breadcrumb del `for` / `while` / `if` / `invoke_macro` anidado | siempre durante pausa |

**Step Into / Over / Out / Continue** (cuando llegue `INVOKE_MACRO` de la mejora #8): cuatro botones diferenciados en el panel flotante, no solo las flechas ←/→.

Fuentes:
- https://docs.uipath.com/studio/standalone/2024.10/user-guide/debugging-actions
- https://docs.uipath.com/studio/standalone/2024.10/user-guide/the-breakpoints-and-bookmarks-panel
- https://docs.uipath.com/studio/docs/the-watch-panel
- https://docs.uipath.com/studio/standalone/2023.4/user-guide/the-immediate-panel

---

### 12. State machine en `PipelineRunner` (4 estados REFramework)

> "La separación Init / Get Transaction Data / Process Transaction / End Process permite re-entrar a Init tras un fallo sistémico sin reiniciar el proceso entero."

Hoy tu `PipelineRunner.run()` ejecuta cada macro y se va. Si la app objetivo se cuelga a la macro 3 de 10, no hay forma de "reabrir la app y seguir". Propuesta:

```python
class PipelineState(Enum):
    INIT = "init"           # abrir aplicaciones, login, anclar ventana
    NEXT_ITEM = "next_item" # obtener la siguiente macro/transacción
    PROCESS = "process"     # ejecutar la macro
    CLEANUP = "cleanup"     # cerrar diálogos sueltos, logout
    END = "end"

# En process, si MemoviSystemError:
#   - cleanup ligero (cerrar popups)
#   - vuelta a INIT (reabre la app)
#   - retry el mismo item (RetryNumber += 1, TransactionNumber sin tocar)
# Si business error: NEXT_ITEM directo
```

Una `init_macro` opcional declarable por pipeline (ej. tu plantilla de arranque) se ejecuta en INIT y se re-ejecuta en cada recovery. Esto es lo que diferencia una automatización de juguete de una de producción.

Fuente: https://github.com/UiPath/ReFrameWork (Main.xaml state machine)

---

### 13. Slow Step graduado (1x→4x) + Highlight Elements overlay

Dos features de UX visual del Studio Debug que son **muy baratas** y dan mucha sensación de "robot pro":

**Slow Step**: cuatro velocidades cíclicas. UiPath lo documenta así:

> "Although called Slow Step, the action comes with 4 different speeds. For example, debugging with Slow Step at 1x runs it the slowest, and fastest at 4x. Each time you click Slow Step the speed changes by one step."
> — Studio docs

En MemoviPro: botón cíclico **🐢 1x / 2x / 3x / 4x / off** en el `StepThroughPanel` que ajusta `delay_entre_pasos_ms` (p. ej. 2000 / 1000 / 500 / 250 / 0). Cuando está activo, el Step-Through avanza solo sin esperar Enter — perfecto para "ver pasar el bot delante" durante demos o auditoría. Compatible con tu navegación ← / → existente.

**Highlight Elements**: antes de ejecutar cada `click`/`type`/`find`, dibujar un overlay translucente sobre el bounding box del control resuelto durante ~400 ms. Implementación PyQt6:

```python
class HighlightOverlay(QWidget):
    def __init__(self, rect_screen: QRect):
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(rect_screen)
        QTimer.singleShot(400, self.close)
    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QPen(QColor("#27ae60"), 3))
        p.drawRect(self.rect().adjusted(1, 1, -1, -1))
```

Llamado en `_click_control` justo antes de actuar. Toggle "Resaltar objetivo" persistido en `QSettings`. Vale tanto para debug como para Run normal — el usuario ve que el bot sabe lo que toca.

Fuente: https://docs.uipath.com/studio/standalone/2024.10/user-guide/debugging-actions

---

### 14. Profile Execution + Test Activity

Dos herramientas de productividad/debug del Studio para detectar cuellos de botella y depurar pasos en aislamiento.

**Profile Execution**:

> "Profile Execution helps you spot performance bottlenecks during workflow executions… provides an analysis of each operation's performance, reflecting a cumulative percentage of every activity's execution time."

En MemoviPro: instrumentar `step_executor` con `time.perf_counter()` por paso y, al terminar, abrir un diálogo con tabla `paso | ms | % del total | n ejecuciones`. Pintar barras horizontales en la fila del paso en la tabla del editor (heatmap rojo/amarillo/verde). Útil para justificar refactors: *"el paso 7 consume el 47% del tiempo, conviene cachear el selector"*.

**Test Activity** (= probar UN paso aislado):

> "The Test Activity context menu option is used for running a test on the currently selected activity. When clicked, the Locals panel opens displaying the variables and arguments in scope."

En MemoviPro: menú contextual del editor → "🧪 Probar este paso" → diálogo con inputs sintéticos (selector, valor, coordenadas) → ejecuta SOLO ese paso en un contexto efímero → muestra resultado + panel Locals. Crítico para depurar un selector flaky **sin reproducir todo el flujo desde el principio**.

Fuentes:
- https://docs.uipath.com/studio/standalone/2023.4/user-guide/profile-execution
- https://docs.uipath.com/studio/docs/test-activities

**Bonus barato** (5 min de código): botón **"📂 Abrir logs"** que ejecute `QDesktopServices.openUrl(QUrl.fromLocalFile(log_dir))` apuntando a `%LOCALAPPDATA%\MemoviPro\Logs\`. Botón gemelo "📁 Abrir carpeta del flujo". Coste ínfimo, ganancia enorme cuando alguien pide soporte.

---

## Roadmap sugerido en 3 tandas

### Tanda A — Quick wins (1-2 sesiones, ROI inmediato)
1. **#3** — Distinguir `BusinessError` vs `SystemError` en el log.
2. **#2** — Score de confianza expuesto en `matchTemplate`.
3. **#1** — OCR con bbox y confidence.
4. **#5** — Convenciones de nombres + descripciones por defecto del recorder.
5. **#13** — Slow Step graduado + Highlight Elements overlay.

### Tanda B — Estructura (3-5 sesiones, robustez)
6. **#4** — Recorder multi-técnica por defecto.
7. **#6** — Linter ligero del YAML.
8. **#7** — `RetryScope` por paso.
9. **#9** — `anchors` en el selector.
10. **#14** — Profile Execution + Test Activity.

### Tanda C — Evolución (sesiones puntuales, valor a largo plazo)
11. **#8** — `INVOKE_MACRO` con args tipados.
12. **#10** — Validation Station PyQt6.
13. **#11** — Step-Through avanzado (breakpoints, tracepoints, Locals/Watch/Immediate/Call Stack).
14. **#12** — State machine en `PipelineRunner`.

---

## Lo que NO conviene copiar de UiPath

Por ser proyecto individual de pocas miles de líneas:

- **Coded Workflows (C#)**: la dualidad XAML/.cs no aplica — tú ya estás en código.
- **Orchestrator / Queues / Assets** distribuidos: overkill.
- **Computer Vision cloud endpoint**: el local Tesseract+OpenCV te basta.
- **ML Extractor entrenado**: para popups de una sola app, regex + Form Extractor (regla #9 — anchors) cubre el 95%.
- **Picture-in-Picture (PiP)** en sesión Windows secundaria: complejidad alta para un usuario.

---

## Fuentes principales

- **REFramework**: https://github.com/UiPath/ReFrameWork
- **Selectors (about/full/partial/wildcards)**: https://docs.uipath.com/activities/other/latest/ui-automation/about-selectors
- **Unified Target / Anchor**: https://docs.uipath.com/activities/other/latest/ui-automation/advanced-descriptor-configuration
- **Object Repository**: https://docs.uipath.com/studio/standalone/2023.4/user-guide/about-object-repository
- **Workflow Analyzer**: https://docs.uipath.com/studio/standalone/2023.10/user-guide/about-workflow-analyzer
- **Retry Scope / Throw / Rethrow / Should Stop**: https://docs.uipath.com/activities/docs/retry-scope
- **Invoke Workflow File + Arguments**: https://docs.uipath.com/activities/other/latest/workflow/invoke-workflow-file
- **Document Understanding (Digitize + Validation)**: https://docs.uipath.com/activities/other/latest/document-understanding/digitize-document
- **CV Scope + CV Activities**: https://docs.uipath.com/activities/other/latest/ui-automation/cv-scope
- **Naming conventions (ST-NMG-001 / ST-NMG-002 / ST-MRD-002)**: https://docs.uipath.com/studio/standalone/2024.10/user-guide/st-nmg-002

> Nota metodológica: `docs.uipath.com` bloqueó WebFetch directo (HTTP 403). Las citas vienen de snippets de WebSearch que extraen pasajes verbatim de esas mismas URLs, cross-checked contra el repo XAML oficial del REFramework y los hilos del foro oficial. Las URLs son accesibles desde un navegador normal.
