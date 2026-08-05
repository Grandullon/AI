# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA** (@PacoVidaIA).
Monitoriza fuentes RSS, Reddit y YouTube, deduplica, evalúa cada item con Claude
Haiku 4.5 según los pilares editoriales del canal, guarda todo en Google Sheets y
envía un resumen ordenado por Telegram.

---

## 1 · Instalación

```bash
cd ia_scout
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 2 · Credenciales

Copia `.env.example` a `.env` y rellena:

| Variable | Descripción |
| --- | --- |
| `ANTHROPIC_API_KEY` | Clave de la API de Anthropic (Claude). |
| `TELEGRAM_BOT_TOKEN` | Token del bot que enviará los avisos. |
| `TELEGRAM_CHAT_ID` | Chat destino (por defecto el de Paco). |
| `GOOGLE_SHEETS_ID` | ID de la hoja donde escribir. |
| `GOOGLE_CREDENTIALS_FILE` | OAuth client secrets (`credentials.json`) descargados de Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client (tipo *Desktop app*). |
| `GOOGLE_TOKEN_FILE` | Se genera automáticamente tras la primera autorización. |

La hoja debe contener dos pestañas:

- **`Hashes`** — dos columnas: `content_hash | timestamp`.
- **`ScoutIA`** — 15 columnas:
  `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`.

## 3 · Primera ejecución

```bash
python ia_scout.py
```

Se abrirá el navegador para autorizar el acceso a Sheets. Confirmar y cerrar.
Se creará `token.json`; las siguientes ejecuciones ya no requieren interacción.

## 4 · Programación (cron)

```
0 */6 * * * cd /ruta/ia_scout && /ruta/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## 5 · Estructura

```
ia_scout/
├── ia_scout.py          # Script principal
├── requirements.txt
├── .env.example         # Plantilla (el .env real NO se commitea)
├── .gitignore
├── README.md
└── logs/                # Creado la primera vez que corres cron
```

## 6 · Notas sobre el entorno

Este pipeline está pensado para un **servidor persistente** (VPS, Mac
siempre encendido, Raspberry, etc.) donde `token.json` sobreviva entre
ejecuciones y el navegador esté disponible para la primera autorización.

Si prefieres correrlo en **GitHub Actions**, cambia el flujo OAuth por una
*service account*: comparte la hoja con el email de la service account y
carga su JSON desde un secret. Así desaparecen `credentials.json` y
`token.json` y no hace falta navegador.
