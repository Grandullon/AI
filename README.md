# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos que monitoriza Reddit, RSS y YouTube,
deduplica, analiza con Claude y envía propuestas por Telegram.

## Instalación

```bash
git clone <repo>
cd ia_scout
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Configuración

1. Copiar plantilla y rellenar credenciales:
   ```bash
   cp .env.example .env
   ```
2. Descargar `credentials.json` desde Google Cloud Console
   (OAuth client secrets tipo *Desktop app*, scope Google Sheets API).
3. Preparar la hoja de cálculo con dos pestañas:
   - `Hashes` — columnas `content_hash | timestamp`
   - `ScoutIA` — 15 columnas descritas en el script

## Primera ejecución

```bash
python ia_scout.py
```

Se abrirá el navegador para autorizar el acceso a Google Sheets.
Se genera `token.json`; las siguientes ejecuciones son silenciosas.

## Cron

```
0 */6 * * * cd /ruta/scout && /ruta/scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Archivos

```
ia_scout/
├── ia_scout.py          # Script principal
├── requirements.txt
├── .env                 # Credenciales (no commitear)
├── .env.example
├── credentials.json     # OAuth client secrets (no commitear)
├── token.json           # Generado automáticamente (no commitear)
├── .gitignore
└── logs/
    └── scout.log
```
