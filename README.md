# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal YouTube **Diario Vida IA**.
Vigila Reddit, blogs RSS y canales de YouTube; deduplica; puntúa cada item con
Claude Haiku; guarda todo en Google Sheets; y envía por Telegram las propuestas
que valen la pena.

## Estructura

```
.
├── ia_scout.py         # Pipeline principal
├── requirements.txt    # Dependencias Python
├── .env.example        # Plantilla de credenciales (copiar a .env)
├── .gitignore          # Excluye .env, token.json, credentials.json
└── logs/               # Se crea al ejecutar (no versionado)
```

## Puesta en marcha (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Rellenar ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, GOOGLE_SHEETS_ID
```

### Google OAuth (una sola vez)

1. En Google Cloud Console → **APIs & Services → Credentials** → **Create
   Credentials → OAuth client ID → Desktop app**.
2. Descargar el JSON como `credentials.json` en la raíz del proyecto.
3. Ejecutar `python ia_scout.py`. En la primera ejecución se abrirá el
   navegador para autorizar acceso a Google Sheets. Al confirmar, se genera
   `token.json`. Las ejecuciones siguientes lo usan sin interacción.

### Hojas requeridas en el Sheet

- **`Hashes`** (2 columnas): `content_hash`, `timestamp`
- **`ScoutIA`** (15 columnas): `content_hash`, `fecha_detectado`, `fuente`,
  `titulo`, `url`, `autor`, `preview`, `keywords`, `notificado`, `vale`,
  `formato`, `puntuacion`, `gancho`, `angulo`, `estado`

## Cron (cada 6 horas)

```
0 */6 * * * cd /ruta/scout && /ruta/scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Por qué no se ejecuta en la nube (Claude Code Web)

Este pipeline está pensado para correr en la máquina de Paco (o servidor
propio), no en el contenedor efímero de Claude Code Web:

- El contenedor de la web es efímero — `token.json` se pierde entre
  ejecuciones.
- El flujo OAuth de Google necesita un navegador local (`run_local_server`),
  imposible en modo desatendido.
- Las credenciales (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`,
  `credentials.json`) no están provisionadas en el entorno remoto.

Para automatizar en la nube: migrar a **service account** de Google (sin
navegador), guardar secretos como variables de entorno / secret manager, y
lanzar desde un cron server / GitHub Action / Cloud Function.
