# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA** (Paco, @PacoVidaIA).

Monitoriza RSS, Reddit y YouTube, deduplica por hash+título, analiza con Claude Haiku 4.5, guarda en Google Sheets y envía un resumen HTML por Telegram.

## Setup local

```bash
# 1. Clonar y entrar
cd ia_scout

# 2. Entorno virtual + dependencias
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Credenciales
cp .env.example .env
# Editar .env con las claves reales

# 4. OAuth Google Sheets
# Descargar credentials.json desde Google Cloud Console
# (OAuth 2.0 Client ID, tipo "Desktop app") y colocarlo aquí.

# 5. Primera ejecución (abrirá navegador para OAuth)
python ia_scout.py
```

Después de la primera ejecución, se genera `token.json` y las siguientes corren sin interacción.

## Scheduling (cron)

```
0 */6 * * * cd /ruta/ia_scout && /ruta/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Estructura del Sheet

- **Hashes** (2 col): `content_hash | timestamp` — dedup persistente.
- **ScoutIA** (15 col): `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`.

## No ejecutar en Claude Code on the Web

El pipeline necesita OAuth con navegador (flujo desktop) y credenciales persistentes en disco. El entorno remoto de Claude Code on the Web es efímero: el `token.json` se pierde entre ejecuciones y el navegador OAuth no puede completarse. Ejecutar solo desde la máquina de Paco (o servidor propio) con cron.
