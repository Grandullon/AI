# MemoviPro — Especificaciones técnicas para integración

**Para:** el equipo/agente del proyecto Linux (Claude Code + OpenClaw + base de datos)
**De:** el proyecto MemoviPro
**Fecha:** 17 de septiembre de 2026
**Autor del programa:** Francisco J. Vidal Gázquez — todos los derechos reservados

---

## 1. Qué es, en una frase

Un robot de escritorio para Windows: **graba lo que haces con el ratón y el
teclado sobre una aplicación y lo repite**, tantas veces como haga falta,
recorriendo una lista de casos.

Está pensado para aplicaciones de escritorio **que no tienen API**. Cuando
existe una API, MemoviPro no es la respuesta — es más lento y más frágil
que una llamada HTTP. Su valor está justo donde no hay otra vía.

## 2. Lo primero que hay que saber antes de diseñar nada

| Restricción | Consecuencia para la integración |
|---|---|
| **Solo Windows** | Depende de la API de accesibilidad de Windows (UIA) y de `pywinauto`. No corre en Linux ni en contenedor. |
| **Necesita sesión gráfica activa** | Mueve el ratón y teclea de verdad. Con la sesión bloqueada o sin escritorio, no funciona. Nada de `docker run`. |
| **Ocupa el equipo mientras trabaja** | Controla el ratón real. Ese equipo no se puede usar para otra cosa a la vez. |
| **Es de un solo usuario** | No hay servidor ni API HTTP. Se invoca por línea de comandos o por su interfaz. |

**Conclusión de arquitectura:** el Linux **no puede ejecutar** MemoviPro. La
integración natural es *Linux = cerebro, Windows = manos*: el Linux decide
qué hay que hacer y recoge los resultados; una máquina Windows lo ejecuta.

## 3. Superficie de integración

Hay **tres puntos de contacto** y ninguno requiere tocar el código.

### 3.1 Entrada: línea de comandos

`memovipro-run.exe` es un ejecutable único, sin instalación.

```bash
# Recorrer una lista de casos
memovipro-run.exe --macro NOMBRE --excel datos.xlsx

# Repetir una macro N veces
memovipro-run.exe --replay NOMBRE --veces 5

# Encadenar varias macros
memovipro-run.exe --pipeline NOMBRE
```

Opciones relevantes para automatizar:

| Opción | Para qué |
|---|---|
| `--dry-run` | Simula sin tocar nada. **Úsalo siempre en la primera pasada de un flujo nuevo.** |
| `--all` | Ignora el punto de reanudación y procesa la lista entera |
| `--no-retry` | No reintenta los fallos al terminar |
| `--no-notify` | No manda correo aunque esté configurado |
| `--velocidad 0` | Sin pausas (más rápido, más frágil) |
| `--data-dir`, `--macros-dir`, `--logs-dir` | Rutas, por si se comparten por red |

### 3.2 Código de salida — el contrato

Esto es lo que debe leer el orquestador:

| Código | Significado | Qué hacer |
|---|---|---|
| **0** | Todo correcto | Seguir |
| **1** | Error de arranque (falta la macro, el Excel no se lee, configuración mal) | **No reintentar**: reintentar no lo va a arreglar |
| **2** | Se ejecutó, pero hubo casos fallidos | Reintentable. Mirar el registro de incidencias |

La diferencia entre 1 y 2 importa: **el 1 no se arregla reintentando** y el 2
a menudo sí.

### 3.3 Salida: ficheros

Todo lo que produce son ficheros planos, legibles desde cualquier sitio:

| Fichero | Formato | Contiene |
|---|---|---|
| `data/incidencias_AAAAMMDD.xlsx` | Excel | Una fila por incidencia |
| `data/checkpoint_*.json` | JSON | Casos ya completados (permite reanudar) |
| `data/screenshots/*.png` | PNG | Captura del momento del fallo |
| `logs/*.log` | Texto | Traza completa |

**Esquema de una incidencia** (lo interesante para volcar a tu base de datos):

```
timestamp · dni · macro · paso_idx · paso_tipo · tipo_error
titulo_popup · texto_popup · screenshot_path · estado · detalle
```

> ⚠️ **Protección de datos.** En su uso actual (aplicación clínica), las
> capturas contienen fichas de pacientes en pantalla y el registro contiene
> identificadores. **No los muevas a la máquina Linux sin decidir antes qué
> se guarda y cuánto tiempo.** El programa ya borra sus capturas a los 30
> días; si se copian fuera, esa limpieza deja de aplicar.

## 4. El formato de macro (YAML)

Una macro es un YAML legible y **generable por un programa**. Esto es lo que
abre la puerta a que el Linux *escriba* trabajo, no solo lo dispare.

```yaml
version: 1
nombre: repartir-it
ventana_principal: GERHONTE      # trozo del título de la ventana de trabajo
pasos:
  - tipo: click_control
    selector: {control_type: Button, name: Aceptar}
    descripcion: Click en Aceptar
    extra:
      fallback_xy: [267, 232]
      win_rel: {title: GERHONTE, proceso: gerhonte.exe, fx: 0.14, fy: 0.23,
                w: 1936, h: 1048, dx: 275, dy: 240}
      texto_ancla: {texto: Aceptar, dx: 0, dy: 0, modo: encima}
      img_b64: "iVBORw0KGgo..."
  - tipo: type_text
    valor: "{DNI}"               # hueco: se rellena con cada caso de la lista
```

**Los huecos `{CAMPO}`** se sustituyen por las columnas del Excel de entrada.
Es el mecanismo por el que se le pasan datos desde fuera: si tu Linux genera
el Excel, controla qué procesa el robot.

**Tipos de paso disponibles** (17): `click_control`, `click_at_xy`,
`click_ocr_text`, `type_text`, `send_keys`, `scroll`, `drag`, `focus_window`,
`window_ensure`, `wait_until`, `wait_for_window`, `sleep`, `close_window`,
`launch_program`, `if_ventana`, `get_text`, `handle_libreoffice_save`.

## 5. Cómo encuentra las cosas en pantalla

Relevante porque explica **por qué a veces falla** y qué se le puede pedir.

Al grabar no guarda solo la posición del ratón: identifica el elemento en el
árbol de accesibilidad de Windows *en el instante del clic*, anota el rótulo
que hay en ese sitio, su posición dentro de la ventana y una miniatura.

Al reproducir prueba esas vías **en orden, de la más fiable a la menos**:

1. Selector del árbol de accesibilidad
2. Posición relativa a la ventana (solo si la ventana mide lo mismo)
3. Reconocimiento de la miniatura en pantalla
4. Texto del rótulo (árbol, y si no, OCR acotado a la ventana)
5. Coordenadas literales

Además, **antes de cada clic comprueba que delante está el programa correcto**.
Si se ha colado otra ventana, espera, intenta recuperar la suya, y solo falla
si tras 15 segundos sigue estorbando.

## 6. Comportamientos que un orquestador debe conocer

| Comportamiento | Qué significa para quien lo invoca |
|---|---|
| **Corte automático** | 3 casos fallidos seguidos detienen la tanda. Devuelve código 2 y el registro dice por qué. No es un fallo del programa: es una protección. |
| **Reanudación** | Por defecto salta los casos ya completados. Una segunda invocación continúa donde se quedó. `--all` lo desactiva. |
| **Huella de la macro** | Si la macro cambia, el punto de reanudación se descarta solo. No se mezclan resultados de versiones distintas. |
| **Reintento propio** | Al terminar reintenta los fallidos con el doble de tiempo de espera, salvo `--no-retry`. |
| **Tecla de pánico** | `Ctrl+Alt+Esc` detiene cualquier ejecución. |

## 7. Tres formas de unir los dos proyectos

Ordenadas de menos a más ambiciosa.

### A. El Linux recoge resultados *(sencillo, útil desde el primer día)*

La carpeta `data/` se comparte o se sincroniza. Un flujo en el Linux lee las
incidencias y las vuelca a la base de datos. Ganas historial, tendencias y
avisos cuando algo se tuerce, sin tocar nada del Windows.

**Requisito:** decidir antes qué campos se copian, por lo de los datos
personales.

### B. El Linux prepara el trabajo *(donde está el valor de verdad)*

El Linux genera el Excel de entrada — filtrando, cruzando datos, aplicando
criterio — y lo deja donde el Windows lo recoge. El Windows solo ejecuta.

Aquí es donde el cerebro está de un lado y las manos del otro, que es el
reparto que funciona.

### C. El Linux dispara y espera *(requiere un agente en el Windows)*

Un pequeño proceso en el Windows escucha peticiones, lanza el ejecutable y
devuelve el código de salida y el resumen. Convierte MemoviPro en un servicio.

**Lo que hay que resolver antes:** quién puede pedirlo, qué pasa si llega una
petición con una tanda ya en marcha, y que la sesión gráfica esté activa.

> **Lo que NO recomiendo:** darle al Linux control directo del escritorio
> Windows por escritorio remoto para que "pulse botones". Duplica lo que
> MemoviPro ya hace, y peor.

## 8. Ficha técnica

- **Lenguaje:** Python 3.11+ · **Interfaz:** PyQt6
- **Automatización:** pywinauto (UIA) · **Captura:** pynput
- **Reconocimiento:** OpenCV (imagen) · Tesseract (texto, opcional)
- **Empaquetado:** PyInstaller, ejecutable único · compilación en GitHub Actions
- **Tamaño:** ~13.700 líneas · **Pruebas:** 559, en verde
- **Dos ejecutables:** `memovipro-gui.exe` (interfaz) y `memovipro-run.exe` (línea de comandos)

## 9. Licencia

Obra original de **Francisco J. Vidal Gázquez**. Todos los derechos
reservados. Cualquier integración es de uso propio del autor; no se cede
ningún derecho de explotación. El texto completo está en el archivo `LICENSE`.
