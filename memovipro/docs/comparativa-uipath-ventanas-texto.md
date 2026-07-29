# UiPath vs MemoviPro: gestión de ventanas y lectura de texto

Investigación verificada contra docs.uipath.com y forum.uipath.com (2 investigadores
independientes). Responde a dos percepciones del usuario:

1. *"UiPath, esté donde esté la ventana, la trae al frente y trabaja sobre ella."*
2. *"A veces es como si reconociera el texto dentro de las aplicaciones."*

Ambas tienen explicación técnica concreta — y en parte ya las tenemos.

---

## 1. Por qué a UiPath "no le importa" dónde esté la ventana

### Lo que hace UiPath

| Mecanismo | Detalle | Fuente |
|---|---|---|
| **Scope de ventana** (Use Application/Browser) | Cada bloque de actividades se "engancha" a UNA ventana identificada por selector. Todas las actividades hijas buscan SOLO dentro de ella (selectores parciales, sin la parte de la ventana). | docs: n-application-card |
| **Open behavior** | `If not open` (default): si ninguna ventana matchea, LANZA la aplicación. `Never` / `Always` como alternativas. Y `Close behavior` al salir del scope. | docs: n-application-card |
| **Activate en cada Click** | La actividad Click tiene una propiedad `Activate` (**default True**): "Bring the UI element to the foreground and activate it before clicking it". Por eso el usuario ve siempre la ventana venir al frente justo antes de cada acción. | docs: n-click |
| **Elemento, no coordenadas** | UiPath NO reproduce coordenadas grabadas. En runtime resuelve el ELEMENTO por selector (atributos, no posición) y clica dentro de su bounding box ACTUAL (con ClickOffset opcional). La ventana puede estar en cualquier sitio: el elemento se encuentra donde esté. | docs: full-versus-partial-selectors, n-click |
| **Input methods sin foreground** | `Simulate` y `Window Messages` funcionan "en background (even if the target app is not in focus)" — la ventana NI SIQUIERA se trae al frente; puede estar de fondo o minimizada. Solo `Hardware Events` exige foreground. | docs: input-methods |
| **WaitForReady** | `None` / `Interactive` / `Complete` — antes de actuar, espera a que la app/elemento estén listos. | docs: ui-activities-properties |
| **Timeout con retry** | Cada actividad reintenta la resolución del selector hasta TimeoutMS (default 30 s) antes de fallar. | docs: ui-activities-properties |

Notas de límite (del foro oficial): con dos ventanas que matchean el mismo selector,
UiPath engancha la primera (problema conocido; se mitiga afinando el selector). Si el
título cambia a mitad de flujo, no hay re-enganche mágico: se usan wildcards en el
selector del scope.

### Lo que ya tiene MemoviPro (equivalencias)

| UiPath | MemoviPro | Estado |
|---|---|---|
| Scope + activación | `ventana_principal` + `auto_anchor`: antes de cada paso, `asegurar_ventana` restaura si está minimizada, maximiza y activa (con el truco anti focus-stealing del Alt-tap, que UiPath ni documenta) | ✅ equivalente (a nivel de macro, no por bloque) |
| Open behavior "If not open" | Plantilla de arranque: `LAUNCH_PROGRAM` + Win+D + `WINDOW_ENSURE` | ✅ manual (no automático) |
| Elemento en runtime | `CLICK_CONTROL` resuelve el selector en runtime y clica el rect actual | ✅ cuando hay selector |
| — | Fallbacks cuando el selector no resuelve: win_rel (fracción de la ventana) → imagen → coordenadas | ⚠️ aquí es donde la posición SÍ puede importar (solo en el último escalón) |
| Timeout con retry | `paso.timeout_s` + `paso.reintentos` con backoff | ✅ |
| WaitForReady | Solo verificación POST-paso (`verificar_ventana`); no hay espera pre-paso adaptativa | ❌ pendiente |
| Simulate (background) | Solo input hardware (ratón/teclado reales) → exige foreground y bloquea el PC | ❌ pendiente |

**Conclusión ventanas:** la sensación de "trae la ventana y trabaja sobre ella" la
tenemos cubierta (anchor + activación agresiva). La diferencia real es doble:
(a) UiPath **nunca** cae a coordenadas — siempre elemento; nosotros solo caemos en el
último escalón de la cascada; y (b) UiPath puede trabajar **sin** traer la ventana al
frente (Simulate), cosa que nosotros no.

---

## 2. Por qué UiPath "reconoce el texto" de las aplicaciones

### La escalera de lectura de UiPath (verificada)

1. **Text attribute (árbol UIA/MSAA)** — la lectura principal NO es OCR: lee el
   `Name`/`Value`/texto que cada control expone en el árbol de accesibilidad de
   Windows (el mismo árbol de los selectores). `Get Text` en modo Default prueba
   Text attribute → FullText y se queda con el primero que devuelve datos.
2. **FullText** — método por defecto del scraping: rápido, "100 % preciso", extrae
   texto visible **y oculto** del elemento; sin coordenadas. Solo escritorio.
3. **Native (GDI)** — extrae el texto visible **con la posición exacta de cada
   palabra** sin OCR, interceptando el dibujo GDI. Limitación: solo apps que
   renderizan con GDI (apps nativas legacy — como GERHONTE, probablemente); no
   funciona en navegadores modernos.
4. **OCR** — último recurso (Citrix/RDP/imágenes/custom-painted): Tesseract,
   Microsoft MODI, UiPath Screen OCR, Azure/Google Cloud, Abbyy. "No es 100 %
   preciso" y es el más lento.

Sobre esa escalera montan: `Click Text` / `Find Text` (localizar una cadena y
clicarla — vía Native), sus variantes OCR (`Click OCR Text` — **exactamente nuestro
CLICK_OCR_TEXT**), y `Data Scraping` (tablas estructuradas leyendo el patrón del
árbol de elementos, no OCR).

### Lo que ya tiene MemoviPro

| UiPath | MemoviPro | Estado |
|---|---|---|
| Text attribute (UIA) | Solo lo usamos en el watchdog de popups (`_texto_completo` de descendants) | ⚠️ existe pero no está expuesto como paso |
| FullText | — | ❌ |
| Native (GDI, coords por palabra) | — (hookear GDI desde Python está fuera de alcance razonable) | ❌ no adoptable |
| OCR | Tesseract con bbox+confianza (`image_to_data`), popups + `CLICK_OCR_TEXT` | ✅ equivalente al escalón OCR |
| Click OCR Text | `CLICK_OCR_TEXT` | ✅ |
| Get Text como actividad | — | ❌ pendiente |
| Data scraping de tablas | — | ❌ (no lo necesitamos hoy) |

**Conclusión texto:** lo que percibes como "reconoce el texto" es sobre todo el
escalón 1 (árbol UIA) usado por todas partes. Nosotros ya leemos ese árbol… pero
solo para popups. Exponerlo como paso (`GET_TEXT`) y como verificación es barato
y es el 80 % de esa sensación. El escalón Native (GDI) es lo único sin equivalente
razonable en nuestro stack; nuestro sustituto es el OCR con coordenadas por palabra
que ya tenemos.

---

## 3. Propuestas concretas (priorizadas)

| # | Propuesta | Qué aporta | Esfuerzo |
|---|---|---|---|
| 1 | **Paso `GET_TEXT`** — leer el texto de un control (selector) con escalera: UIA Name/Value → texto de descendants → OCR del rect del control. Guardar el resultado en una variable de contexto (`{TEXTO_LEIDO}`) usable en pasos siguientes, y opción "verificar que contiene X" | La sensación "lee la app" de UiPath; permite verificaciones reales ("el campo dice 'Guardado'") en vez de solo esperar ventanas | Medio |
| 2 | **`verificar_texto` post-paso** — como `verificar_ventana`, pero comprobando que un control/zona contiene un texto (misma escalera del punto 1) | Verificaciones mucho más finas que "apareció la ventana" | Bajo (reusa el #1) |
| 3 | **`metodo_input: simulate`** — usar patrones UIA (`invoke()`, `set_text()`) como método primario con fallback a hardware | Trabajar con la ventana de fondo, sin robar el ratón: el PC queda usable durante los lotes (la mayor ventaja restante de UiPath) | Medio |
| 4 | **`esperar_listo` pre-paso (WaitForReady)** — `ctrl.wait('visible enabled ready')` configurable por paso, en vez de sleeps fijos | Elimina la fragilidad de los delays grabados cuando la app tarda distinto | Bajo |
| 5 | **Open behavior en `WINDOW_ENSURE`** — opción "si la ventana no existe, lanzar este exe y esperar" (integra lo que hoy hace la plantilla de arranque en un solo paso) | Macros autosuficientes estilo scope de UiPath | Bajo |
| 6 | **Aviso de multi-match** — si el patrón de ventana matchea DOS ventanas, loguear warning con los títulos (UiPath sufre el mismo problema; al menos hacerlo visible) | Diagnóstico de "clicó en la ventana equivocada" | Bajo |

**No adoptar:** el hook GDI de Native (complejidad de driver/inyección, frágil,
innecesario teniendo UIA + OCR con bbox) y ChromiumAPI (no automatizamos navegador).

---

## Fuentes

- Use Application/Browser: https://docs.uipath.com/activities/other/latest/ui-automation/n-application-card
- Click (Activate, ClickOffset): https://docs.uipath.com/activities/other/latest/ui-automation/n-click
- Input methods: https://docs.uipath.com/activities/other/latest/ui-automation/input-methods
- Full vs partial selectors: https://docs.uipath.com/activities/other/latest/ui-automation/full-versus-partial-selectors
- Screen scraping (FullText/Native/OCR): https://docs.uipath.com/studio/standalone/2024.10/user-guide/output-or-screen-scraping-methods
- Get Text (Modern): https://docs.uipath.com/activities/other/latest/ui-automation/n-get-text
- Click OCR Text: https://docs.uipath.com/activities/other/latest/ui-automation/click-ocr-text
- Data scraping: https://docs.uipath.com/studio/standalone/2024.10/user-guide/about-data-scraping
- UIA/MSAA (Microsoft): https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-msaa
- Foro (Simulate/WM en background): https://forum.uipath.com/t/how-simulate-type-click-and-send-window-messages-works/299749

> Nota: docs.uipath.com bloquea la descarga directa (403); las citas provienen de los
> extractos indexados de esas mismas URLs, cruzados con el foro oficial.
