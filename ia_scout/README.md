# IA Scout

Pipeline de detección y análisis de contenido para el canal YouTube **Diario Vida IA**
(Paco, [@PacoVidaIA](https://www.youtube.com/@PacoVidaIA)).

Cada ejecución:

1. Descarga posts nuevos de Reddit (JSON API), blogs (RSS) y canales de YouTube (Atom).
2. Deduplica contra la hoja `Hashes` (Google Sheets) y contra el propio lote.
3. Analiza cada item nuevo con Claude (`claude-haiku-4-5-20251001`) usando el brief editorial del canal.
4. Guarda el análisis completo en la hoja `ScoutIA` y el hash en `Hashes`.
5. Envía a Telegram un resumen HTML con las propuestas `vale=SI`, ordenadas
   por formato (largos primero) y puntuación.

## Instalación

```bash
cd ia_scout
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # rellena con tus tokens
# Descarga credentials.json desde Google Cloud Console (OAuth client type=Desktop)
# y colócalo en esta carpeta.
```

## Primera ejecución

```bash
python ia_scout.py
```

Se abrirá el navegador para autorizar el acceso a Google Sheets. Al confirmar,
se guarda `token.json` y las siguientes ejecuciones son silenciosas.

## Cron (cada 6 h)

```
0 */6 * * * cd /ruta/absoluta/ia_scout && /ruta/absoluta/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Google Sheet — estructura esperada

Hoja `Hashes` (2 columnas):

| A: content_hash | B: timestamp |

Hoja `ScoutIA` (15 columnas):

| A: content_hash | B: fecha_detectado | C: fuente | D: titulo | E: url |
| F: autor | G: preview | H: keywords | I: notificado | J: vale |
| K: formato | L: puntuacion | M: gancho | N: angulo | O: estado |

## Notas

- Hashes: base64 truncado (compatible con los guardados por n8n).
- Rate limit Claude: 0.5 s entre llamadas.
- Reddit devuelve 429 con cierta frecuencia; el fetcher salta el subreddit y sigue.
- Nunca subir `.env`, `credentials.json` ni `token.json` a git.
