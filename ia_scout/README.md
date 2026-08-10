# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA** (Paco, @PacoVidaIA).
Monitoriza RSS + Reddit + YouTube, deduplica contra Google Sheets, puntúa con Claude y envía un resumen por Telegram.

## Setup

1. **Instalar dependencias**
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Credenciales Google** (una sola vez)
   - En Google Cloud Console, crea un OAuth Client ID de tipo *Desktop*.
   - Descarga el JSON como `credentials.json` en esta carpeta.
   - Activa la Google Sheets API en el proyecto.

3. **Variables de entorno**
   - Copia `.env.example` a `.env` y rellena las claves reales.

4. **Primera ejecución** (interactiva, abre navegador para autorizar)
   ```bash
   python ia_scout.py
   ```
   Genera `token.json` que se reutiliza en las siguientes ejecuciones.

## Programación (cron)

```
0 */6 * * * cd /ruta/ia_scout && /ruta/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Hoja de Google Sheets

- ID: definido en `.env` (`GOOGLE_SHEETS_ID`)
- Pestaña `Hashes` — dos columnas: `content_hash`, `timestamp`
- Pestaña `ScoutIA` — 15 columnas según el esquema en `ia_scout.py`

## Notas

- Los hashes usan base64 truncado a 20 chars para mantener compatibilidad con los ya almacenados.
- La analítica corre en `claude-haiku-4-5-20251001` con `max_tokens=800`.
- Cualquier fallo por fuente se registra pero no aborta el ciclo.
