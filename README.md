# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA**. Cada
ejecución revisa Reddit, RSS de blogs y RSS de YouTube; deduplica frente a
la hoja "Hashes"; puntúa cada novedad con Claude Haiku 4.5; guarda todo en
"ScoutIA"; y envía por Telegram sólo las propuestas puntuadas `SI`.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # rellenar con las claves reales
# copiar credentials.json (OAuth client secrets desde Google Cloud Console)
python ia_scout.py        # primera vez abre navegador para OAuth de Google
```

En la primera ejecución se crea `token.json`; las siguientes ya no necesitan
navegador.

## Cron

```
0 */6 * * * cd /ruta/scout && /ruta/scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Hoja de cálculo

Dos pestañas obligatorias en la hoja de Google Sheets referenciada por
`GOOGLE_SHEETS_ID`:

- **Hashes**: columna A `content_hash`, columna B `timestamp_utc`
- **ScoutIA**: 15 columnas —
  `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`

## Notas

- Compatibilidad con hashes ya presentes: se usa `base64(titulo[:80]+"_"+url)[:20]`
  (Opción A del prompt de referencia).
- `time.sleep(0.5)` entre llamadas a Claude para no rozar rate limits.
- Errores por fuente no abortan el ciclo — se saltan y se continúa.
