# Dashboard diario de Ausencias e IT — HUVN

Sustituye el correo diario con los Excel adjuntos por **un informe HTML que se
genera solo** y vive en la carpeta compartida. Quien tiene permiso sobre la
carpeta lo abre con doble clic. Quien no lo tiene, no ve nada.

Es la evolución natural del `DashboardHUVN.exe` que ya usáis: mismo enfoque
(Python + PyInstaller + `config.json` + plantilla HTML), pero en vez de decir
*qué ficheros existen*, dice **qué está pasando con las ausencias**.

---

## Qué muestra que hoy no se ve en el Excel

| Indicador | Por qué importa |
|---|---|
| Ausencias vigentes y variación diaria | La cifra del día en una sola pantalla |
| Altas e ITs nuevas | El movimiento real, no solo el saldo |
| **Sustituto IT** con nombre, en cada tabla | Se ve quién cubre la plaza y cuáles no tiene nadie |
| Evolución de los últimos volcados | Si la curva sube o baja, con tendencia por unidad |
| Concentración por Dirección / Servicio / Centro | Dónde está el problema, no solo cuánto |
| **Vigilancia a partir de 500 días** | La lista de seguimiento, con los que superan los 18 meses marcados aparte |
| Duración media y mediana, tramos de duración | Distingue el catarro de tres días de la baja de dos años |
| Repuntes anómalos por servicio | Avisa cuando una unidad se sale de su media del periodo |
| Tasa sobre plantilla activa | Solo si está el fichero PA del día; es opcional |

Sobre el volcado real del 26/08/2026 el informe detecta, entre otras cosas,
**322 ausencias sin sustituto asignado (53,7 %)** y los casos que superan el umbral
de vigilancia de 500 días. Ninguno de esos datos es visible hoy abriendo el Excel.

## Cómo se usa

1. Se deja la carpeta del programa dentro de `\\Alhambra\grupo$\HUVN-PERSONAL-ACTIVO`.
2. Doble clic en `DashboardIT.exe`. Se genera el informe y se abre en el navegador.
3. Con una **tarea programada** a las 9:15, el HTML ya está actualizado antes de
   que nadie llegue: los compañeros solo abren `Dashboard-IT.html`.

```
DashboardIT.exe --headless        genera sin abrir ventana (tarea programada)
DashboardIT.exe --demo            datos inventados, para enseñarlo en una reunión
DashboardIT.exe --anonimo         genera solo la versión sin datos personales
DashboardIT.exe --fecha 2026-08-26   informe de un día concreto
DashboardIT.exe --dias 40         amplía la serie histórica
```

## Dos versiones en cada ejecución

| Fichero | Contenido | Para quién |
|---|---|---|
| `Dashboard-IT.html` | Con nombre y DNI | Unidad de Personal (uso interno) |
| `Dashboard-IT-direccion.html` | Solo cifras agregadas, **sin nombres ni DNI** | Dirección, comisiones, juntas |

La segunda se puede compartir sin exponer datos personales. Se desactiva con
`"generar_version_direccion": false`.

## Protección de datos

- Todo el proceso ocurre dentro de la red del hospital. El HTML **no hace ni una
  sola petición a internet**: no carga fuentes, ni librerías, ni analítica.
- El control de acceso es el de la carpeta compartida (NTFS). No hay usuarios ni
  contraseñas que mantener.
- El fichero nominal contiene datos de carácter personal y datos de salud: debe
  vivir en una carpeta con permisos restringidos, igual que los Excel de hoy.
  Para difusión más amplia, usar la versión de dirección.

## Configuración

Al primer arranque se crea `config_it.json` junto al ejecutable. Se edita con el
Bloc de notas y **no hace falta recompilar**:

```jsonc
{
  "carpeta_it":    "\\\\Alhambra\\grupo$\\HUVN-PERSONAL-ACTIVO\\IT DIARIA\\IT DIARIA\\{YYYY}",
  "patron_it":     "IT-HVN-{YYYY}-{MM}-{DD}",
  "carpeta_altas": "\\\\Alhambra\\grupo$\\HUVN-PERSONAL-ACTIVO\\IT DIARIA\\ALTAS IT\\{YYYY}",
  "patron_altas":  "ALTAS IT A {YYYY}-{MM}-{DD}",
  "salida":        "\\\\Alhambra\\grupo$\\HUVN-PERSONAL-ACTIVO\\Dashboard-IT.html",
  "dias_serie": 20,
  "dias_vigilancia": 500,
  "generar_version_direccion": true
}
```

Busca dentro de la carpeta del año y de sus subcarpetas de mes, así que da igual
que se llamen `MARZO`, `03-Marzo` o `marzo`.

## Cómo lee los volcados

Comprobado contra los ficheros reales:

| Columna del Excel | Se usa como |
|---|---|
| `Fecha IT` | **Inicio de la ausencia** |
| `FECHA INICIO` / `FECHA FINAL` | Fechas del contrato — *no* de la IT |
| `Dias de IT` | Duración a la fecha del volcado |
| `COD_INC` | Código de incidencia, agrupado en familias |
| `SUSTITUTO_IT` | Vacío = plaza sin cubrir |
| `DIRECCIÓN`, `CENTRO_EQ`, `SERVICIO` | Ejes de agrupación |

Se lee la hoja `IT DIARIA` (no la hoja de trabajo `bae`) y las cabeceras se
detectan solas, con tolerancia a tildes, mayúsculas y filas de título.

**Pendiente de confirmar con la unidad:** el agrupamiento de `COD_INC`. Hoy se
agrupa `ITE/ITA/ITN/ITI/ITR` como incapacidad temporal, `IM*` como maternidad,
`PAT/PAA` como paternidad y `PL3` como permisos. `ITR` es el que conviene
revisar: en el volcado real, 23 de sus 49 casos tienen sustitución por
*Baja Maternal*. Se cambia en `config_it.json`, apartado `familias`.

## Requisitos

Ninguno en los equipos de los compañeros: es un HTML y se abre con el navegador.

Para generar el informe basta con el `.exe`. Si se ejecuta como script, Python
3.9 o superior **sin instalar nada**: la lectura de `.xlsx` está hecha con la
librería estándar (`zipfile` + `xml`), no con pandas ni openpyxl.
