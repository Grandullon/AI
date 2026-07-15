# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA**.

Cada ejecución:

1. **Fetch** — Reddit (6 subs) + RSS blogs (2) + YouTube (8 canales).
2. **Dedup** — hashes almacenados en la hoja `Hashes` + fingerprint por título.
3. **Análisis Claude** — puntúa 1–10, decide SI/NO, propone formato + gancho + ángulo.
4. **Guarda** — cada análisis en la hoja `ScoutIA` (15 columnas).
5. **Telegram** — envía resumen con las propuestas `SI` ordenadas (largo → short).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Edita .env con tus credenciales
```

### Google Sheets — dos formas de autenticar

**Recomendada para cron/scheduled (headless):** service account.

1. En Google Cloud Console, crea un service account y descarga su JSON.
2. Guárdalo como `service_account.json` en esta carpeta (o pon el JSON completo
   en la variable `GOOGLE_SERVICE_ACCOUNT_JSON`).
3. **Comparte** el Google Sheet con el `client_email` del JSON, con permiso de
   **Editor**.
4. Habilita la API de Google Sheets en el proyecto de Cloud.

**Solo para desarrollo local con navegador:** OAuth desktop.

1. Descarga `credentials.json` desde Google Cloud Console (OAuth 2.0 → Desktop).
2. La primera ejecución abrirá el navegador para autorizar y creará `token.json`.

## Ejecución

```bash
python ia_scout.py
```

## Cron (cada 6 h)

```
0 */6 * * * cd /ruta/scout && /ruta/venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Estructura esperada de la hoja

- **Hashes** (2 col): `content_hash | timestamp` — se crea si no existe.
- **ScoutIA** (15 col): `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado` — se crea si no existe.

## Ficheros que NO se suben a git

`.env`, `token.json`, `credentials.json`, `service_account.json`, `logs/*.log`
(ver `.gitignore`).
