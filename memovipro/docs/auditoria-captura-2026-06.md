# Auditoría MemoviPro — captura de movimiento y programa completo

Fecha: 2026-06 · Método: 3 revisores independientes en paralelo (pipeline de captura, round-trip grabación→reproducción, barrido general) + verificación manual de los hallazgos de mayor gravedad. Los bugs marcados **[2×]** fueron confirmados por dos revisores de forma independiente.

## Resumen ejecutivo

- **27 hallazgos reales** (0 inventados: todos con fichero:línea verificados).
- Los más graves para tu uso diario en GERHONTE:
  1. **"hola mundo" se reproduce como "holamundo"** — los espacios se pierden al reproducir.
  2. **Teclado español roto para símbolos**: `@ # € [ ] { }` (AltGr) se graban como atajos, no como texto. Un email o contraseña con `@` se reproduce mal.
  3. **La grabación puede morir en silencio** — una excepción en un callback mata el listener de pynput y el contador sigue como si nada (síntoma que ya sufriste: "captura N eventos y luego nada").
  4. **"Editar" en la pestaña Programación no funciona NUNCA** (descuadre de prefijo `MemoviPro_`).
  5. **Si tienes el Excel de incidencias abierto, se aborta el lote entero de DNIs.**
  6. **Seguridad**: un texto grabado que contenga `{SECRET:nombre}` teclea el secreto real al reproducir.

---

## A. Captura de movimiento (recorder) — el foco pedido

### P0 — corrompen la grabación o el replay

**A1. Espacios perdidos al reproducir** — `core/recorder.py:558` + `core/player.py:375`
La barra espaciadora no tiene `.char` en pynput → corta el buffer de texto y se emite como paso `send_keys " "`. El replay envía `send_keys` **sin** `with_spaces=True` (default de pywinauto: descartar espacios) → el espacio no se teclea. "hola mundo" → 3 pasos → replay "holamundo". Además `Ctrl+Espacio` genera el token `"^ "` → `"^"` huérfano → excepción.
**Fix:** añadir el espacio al buffer de texto como un carácter más (no fragmentar); mapear `space` a `{SPACE}` cuando forme parte de un atajo.

**A2. [2×] AltGr (teclado español): `@ # € [ ] { } \` grabados como atajo** — `core/recorder.py:113,498`
AltGr = Ctrl+Alt para Windows. `_modifier_for` lo mapea a "alt" y Windows añade un ctrl sintético → al teclear `@` el recorder ve modificadores activos y lo trata como atajo `send_keys "^%@"` en vez de texto. Con `[ { }` el token queda además sintácticamente roto. Impacto directo: emails, rutas y contraseñas.
**Fix:** si `key.char` no es None y los modificadores son exactamente {ctrl, alt} (huella de AltGr), tratar como texto.

**A3. Callbacks de pynput sin blindar → la grabación muere en silencio** — `core/recorder.py:350,448,478,519`
pynput detiene el listener si un callback lanza una excepción. Ninguno de los 4 callbacks tiene try/except envolvente. Si algo falla a mitad, la UI sigue "grabando" pero ya no captura. Coincide con el síntoma que reportaste en su día.
**Fix:** try/except + `logger.exception` en el cuerpo completo de los 4 callbacks.

**A4. [2×] Atajos con caracteres especiales generan tokens rotos** — `core/recorder.py:507-510`
`Ctrl + '+'` (zoom) → token `"^+"` = prefijo Ctrl+Shift sin tecla → `KeySequenceError` o pulsación fantasma al reproducir. Igual con `( ) { } % ~`. El escape (`escape_send_keys`) existe pero solo se aplica al TYPE_TEXT, nunca a la base de los atajos.
**Fix:** `base = escape_send_keys(char)` en la rama de atajo del recorder.

**A5. Ctrl+letra probablemente graba caracteres de control** — `core/recorder.py:494-510`
pynput en Windows entrega `key.char = '\x01'` para Ctrl+A (no `'a'`) → token grabado `"^\x01"`, irreproducible y con descripción ilegible. Pendiente de confirmar en Windows real, pero muy probable.
**Fix:** si hay ctrl activo y `ord(char) < 32`, reconstruir la letra (`chr(ord(char)+96)`) o usar `key.vk`.

### P1 — pierden eventos o ensucian la macro

**A6. Dos botones de ratón solapados → se pierden AMBOS clics** — `core/recorder.py:371-385`
`_press_pendiente` es un slot único. Press izq → press der (sobrescribe) → release izq (botón no coincide, se anula el pendiente) → release der (huérfano). Cero eventos.
**Fix:** un pendiente por botón (`dict[str, dict]`).

**A7. El clic en "Detener" (y los arrastres del panel flotante) se graban como pasos** — `core/recorder.py:350-396`
Solo F9 está filtrado. El clic físico llega al hook antes de que Qt procese el botón → el último paso de la macro clica donde estaba el botón Detener.
**Fix:** filtrar eventos cuyo punto caiga en ventanas del propio proceso MemoviPro (comparar PID vía `from_point`).

**A8. Teclas no mapeadas descartadas sin aviso** — `core/recorder.py:554-566`
Insert, teclas del numpad, print_screen, menú… → `None` → evento perdido sin log.
**Fix:** ampliar el mapping (`{INS}`, `{PRTSC}`…) y loguear el descarte.

**A9. El timestamp del texto es el del ÚLTIMO carácter** — `core/recorder.py:535`
El delay antes de un paso TYPE_TEXT incluye toda la duración del tecleo → replay: espera larga + tecleo en ráfaga. Orden correcto, ritmo distorsionado.
**Fix:** guardar el ts del primer carácter en `_BufferTexto`.

**A10. "Cerrar sin procesar" emite la macro igualmente** — `ui/record_dialog.py:272-291`
Si el worker de resolución sigue vivo al cancelar, cuando termina hace `accept()` sobre un diálogo ya rechazado y emite `macro_capturada` — el editor puede recibir una macro que cancelaste.
**Fix:** flag de cancelación consultado en `_on_macro_ready`.

### P2 — casos límite

- **A11.** Dead keys españolas (´ ¨ `) sin manejo — puede grabarse "´a" en vez de "á" (`core/recorder.py:544`). Confirmar en Windows.
- **A12.** Un scroll/tecla entre los dos clics de un doble clic rompe la fusión → dos clics simples (`core/recorder.py:406`).
- **A13.** Atributo inconsistente `_main_window_was_visible` vs `_main_was_visible` en record_dialog (código muerto que confunde).
- **A14.** `FLUSH_TEXT_AFTER_S` es código muerto: todas las llamadas usan `force=True` y no hay timer.

---

## B. Reproducción (round-trip con lo grabado)

**B1. [ALTA] Título de ventana usado como regex sin escapar** — `core/player.py:723`
El fallback `win_rel` interpola el título real capturado en `title_re=f".*{title}.*"`. Un título con corchetes ("Doc1 [Modo compatibilidad]") se convierte en clase de caracteres → **puede clicar en la ventana equivocada**; "Notepad++" lanza `re.error` y mata el fallback en silencio.
**Fix:** `re.escape(title)` (solo ahí — los patrones configurados a mano deben seguir siendo regex).

**B2. [ALTA — seguridad] El texto grabado pasa por el motor de placeholders** — `core/step_model.py:221,258`
Si el texto tecleado (o un YAML editado) contiene `{DNI}`, `{MM}`, `{HH}` o cualquier nombre de columna del Excel, se sustituye en el replay en vez de teclearse literal. Y `{SECRET:nombre}` **resuelve y teclea el secreto real** — vía de exfiltración si alguien te pasa un YAML manipulado.
**Fix:** flag `raw: true` en pasos grabados (salta `render_placeholders`), o escapar llaves al grabar.

**B3. [MEDIA] CLICK_AT_XY ignora los datos robustos que el recorder guarda** — `core/player.py:361-366`
El recorder guarda `win_rel` e `img_b64` también en los clics sin selector, pero el replay de CLICK_AT_XY solo usa coordenadas absolutas. Toda la cascada robusta vive solo en CLICK_CONTROL.
**Fix:** reutilizar la cascada (win_rel → imagen → xy) también en CLICK_AT_XY.

**B4. [MEDIA] Scroll horizontal reproducido como vertical + errores tragados** — `core/player.py:451-455`
`wheel = dy if dy != 0 else dx` mete el desplazamiento horizontal en la rueda vertical. Y los fallos de scroll/drag solo hacen `logger.warning` → cuentan como paso exitoso sin incidencia.

**B5. [MEDIA] DRAG de un solo salto** — `core/player.py:467-471`
press → move directo → release. Muchos controles (scrollbars, sliders, drag&drop) necesitan movimientos intermedios para *iniciar* el arrastre → se reproduce como simple clic.
**Fix:** interpolar 10-20 puntos con pausas de ~15 ms.

**B6. [MEDIA] velocidad=0 sin suelo mínimo** — `core/player.py:316-317`
Dos clics intencionados sobre el mismo punto (separados 1 s al grabar) caen dentro del umbral de doble clic del sistema → la app los lee como doble clic. Menús sin tiempo de abrirse.
**Fix:** suelo de ~0.12 s entre pasos incluso a velocidad 0.

**B7-B9. [BAJA]** Win+Click pierde el Win al reproducir (`player.py:898,908`); DPI awareness no declarada por la app (funciona de rebote por el import de pywinauto/Qt6); una columna del Excel llamada "enter"/"tab"/"f1" sustituiría tokens de send_keys.

Puntos verificados y **correctos** (refutados): TYPE_TEXT con escape+with_spaces, gestión de modificadores held entre pasos (sin doble-Ctrl, liberación en finally), doble clic y botón en toda la cascada de fallbacks.

---

## C. Resto del programa

**C1. [ALTO — verificado a mano] "Editar" en Programación no funciona nunca** — `ui/schedule_panel.py:529 vs 543,708`
La metadata se guarda con el nombre SIN prefijo, pero la tabla lista `MemoviPro_<nombre>` → Editar carga `MemoviPro_x` → siempre `None` → "Sin datos para editar". Eliminar deja JSONs huérfanos.
**Fix:** `nombre.removeprefix("MemoviPro_")` en `_nombre_seleccionado()`.

**C2. [ALTO — verificado a mano] Excel de incidencias abierto = lote entero abortado** — `core/excel_logger.py:94` + `core/runner.py:108`
`wb.save()` lanza `PermissionError` si tienes el fichero abierto en Excel, y `append_ok` está FUERA del try → mata la pasada completa de DNIs (y la incidencia se pierde).
**Fix:** reintentos con backoff + volcado a CSV de emergencia si persiste; nunca propagar desde el logging.

**C3. [ALTO — solo afecta al .exe] Rutas sobre `__file__` apuntan a la carpeta temporal `_MEIPASS`** — `ui/run_panel.py:28`, `ui/step_editor.py:470,546`
En el build onefile, `CONFIG_PATH` resuelve al config bundleado (ignora tu `config.json` editado — el email SMTP no funciona), y los `data/screenshots` de "paso a paso / hasta aquí / desde aquí" van a una carpeta temporal **que se borra al cerrar**.
**Fix:** patrón `sys.executable` si `sys.frozen` (como ya hacen app.py/cli.py).

**C4. [MEDIA] La tecla de pánico (Ctrl+Alt+Esc) no aborta las cadenas** — `ui/main_window.py:140-143` — llama a run/replay pero no a `pipeline_panel.abort()`.

**C5. [MEDIA] Sin `closeEvent`**: cerrar MemoviPro con una ejecución en marcha deja el hilo automatizando el escritorio sin control.

**Robustez (5):** checkpoint con read-modify-write sin fusión bajo lock (GUI + tarea programada a la vez se machacan los OK → DNIs duplicados) y `reset()` pierde el fingerprint; guardado del Excel no atómico (un kill a mitad corrompe el xlsx para siempre) y workbooks read-only sin `close()`; `keyring = None` sin bindear en el except (4 tests fallan en entorno limpio); `cli.py --replay` ignora la config del watchdog que `--macro` sí aplica; `file_lock` continúa sin lock al agotar el timeout justo cuando más importa.

---

## Plan de corrección propuesto (3 tandas)

**Tanda 1 — Captura fiable (los que corrompen tus macros):** A1 espacios, A2 AltGr, A3 callbacks blindados, A4 escape de atajos, A5 Ctrl+letra, A7 filtro de clics propios. + B1 re.escape y B2 raw/placeholders (van de la mano al reproducir lo grabado).

**Tanda 2 — Operación diaria:** C1 Editar programación, C2 Excel abierto, C3 rutas frozen, C4 pánico en pipelines, C5 closeEvent, B3 cascada en CLICK_AT_XY, B6 suelo a velocidad 0.

**Tanda 3 — Pulido:** A6, A8-A14, B4, B5, B7-B9 y las 5 mejoras de robustez.

Todo cambio con tests y doble auditoría independiente (mínimo 2 OK) como venimos haciendo.
