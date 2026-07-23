# IA Scout

Pipeline de inteligencia de contenidos para el canal YouTube **Diario Vida IA** (@PacoVidaIA).

Monitoriza Reddit, blogs RSS y canales de YouTube, evalúa cada novedad con Claude según los pilares editoriales del canal (NotebookLM, IA práctica para trabajadores del conocimiento, automatización), guarda todo en Google Sheets y envía por Telegram las propuestas marcadas como aptas.

## Estructura

```
.
├── ia_scout.py          # Pipeline completo
├── requirements.txt     # Dependencias Python
├── .env.example         # Plantilla de credenciales
├── .gitignore
└── logs/                # Se crea al ejecutar
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate            # Linux/macOS
pip install -r requirements.txt
cp .env.example .env
```

Rellena `.env` con tus claves reales.

## Google Sheets — OAuth

1. En [Google Cloud Console](https://console.cloud.google.com/) crea un proyecto, habilita la **Google Sheets API** y genera credenciales OAuth de tipo **Aplicación de escritorio**.
2. Descarga el JSON como `credentials.json` en la carpeta del proyecto.
3. La primera ejecución abrirá el navegador para autorizar; se guardará `token.json` para las siguientes.

La hoja destino debe tener dos pestañas:
- **`Hashes`** — 2 columnas: `content_hash`, `timestamp`
- **`ScoutIA`** — 15 columnas: `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`

## Ejecución manual

```bash
python ia_scout.py
```

## Programación con cron

```bash
crontab -e
```

Añade la línea (cada 6 h):

```
0 */6 * * * cd /ruta/al/proyecto && /ruta/al/proyecto/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Notas operativas

- **No ejecutar en entornos efímeros** (contenedores web, CI de un solo uso): el flujo OAuth de Google requiere navegador la primera vez y persistencia de `token.json`.
- Reddit exige `User-Agent`; ya está configurado.
- Rate limit Claude: 0,5 s entre peticiones.
- Si un subreddit o feed falla, el pipeline continúa con los demás.
- Los hashes usan base64 truncado para mantener compatibilidad con los ya almacenados.
