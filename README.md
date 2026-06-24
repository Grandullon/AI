# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal YouTube "Diario Vida IA".
Monitoriza RSS / Reddit / YouTube, deduplica, analiza con Claude, guarda en
Google Sheets y envía resumen por Telegram.

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # rellenar con las claves reales
```

Coloca `credentials.json` (OAuth client secrets de Google Cloud Console) en la
carpeta del proyecto. La primera ejecución abrirá el navegador para autorizar
y generará `token.json` automáticamente.

## Ejecución

```bash
python ia_scout.py
```

## Estructura esperada de Google Sheets

- Hoja **`Hashes`** (2 columnas): `content_hash | timestamp`
- Hoja **`ScoutIA`** (15 columnas): `content_hash | fecha_detectado | fuente |
  titulo | url | autor | preview | keywords | notificado | vale | formato |
  puntuacion | gancho | angulo | estado`

## Cron sugerido

```cron
0 */6 * * * cd /ruta/scout && python ia_scout.py >> logs/scout.log 2>&1
```
