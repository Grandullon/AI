# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal YouTube **Diario Vida IA**
(Paco, [@PacoVidaIA](https://youtube.com/@PacoVidaIA)).

Cada ejecución:

1. Lee RSS (Ethan Mollick, Simon Willison), 8 canales de YouTube (RSS oficial) y
   6 subreddits vía JSON API.
2. Normaliza cada item a un esquema común.
3. Deduplica contra la hoja `Hashes` de Google Sheets + memoria del ciclo.
4. Puntúa cada novedad con Claude Haiku 4.5 usando el prompt editorial del canal
   (pilar NotebookLM, audiencia no-dev, estilo anti-gurú).
5. Guarda todo lo procesado en la hoja `ScoutIA` y anota el hash.
6. Envía a Telegram un resumen ordenado con las propuestas marcadas `SI`.

## Instalación

```bash
cd ia_scout
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # y rellena las credenciales
```

## Credenciales de Google (OAuth de escritorio)

1. Google Cloud Console → *APIs & Services* → habilita **Google Sheets API**.
2. *Credentials* → *Create credentials* → *OAuth client ID* → tipo **Desktop app**.
3. Descarga el JSON y guárdalo como `credentials.json` en `ia_scout/`.
4. Primera ejecución (`python ia_scout.py`): se abrirá el navegador; autoriza y
   se creará `token.json` automáticamente. Las siguientes ejecuciones son silenciosas.

> `credentials.json` y `token.json` están en `.gitignore`. No los subas.

## Google Sheets — estructura esperada

Hoja de cálculo: `GOOGLE_SHEETS_ID` (ya en `.env.example`).

Pestañas requeridas:

- **`Hashes`** — columnas: `content_hash`, `timestamp`. Se crea sola si no existe.
- **`ScoutIA`** — columnas A–O:

  | Col | Campo             |
  |-----|-------------------|
  | A   | content_hash      |
  | B   | fecha_detectado   |
  | C   | fuente            |
  | D   | titulo            |
  | E   | url               |
  | F   | autor             |
  | G   | preview           |
  | H   | keywords          |
  | I   | notificado        |
  | J   | vale              |
  | K   | formato           |
  | L   | puntuacion        |
  | M   | gancho            |
  | N   | angulo            |
  | O   | estado            |

## Ejecución manual

```bash
cd ia_scout
python ia_scout.py
```

## Programación con cron (cada 6 horas)

```bash
crontab -e
# añade:
0 */6 * * * cd /ruta/absoluta/ia_scout && /ruta/absoluta/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

Crea la carpeta de logs una vez: `mkdir -p /ruta/absoluta/ia_scout/logs`.

## Compatibilidad con hashes n8n existentes

El script usa la **Opción A** de hashing (base64 truncado a 20 chars con `+/=`
sustituidos por `x`) — idéntica al flujo anterior en n8n. Los hashes que ya
tengas en la hoja `Hashes` siguen siendo válidos y evitan duplicados.

## Fuentes monitorizadas

- **Reddit** (JSON API): `notebooklm`, `PromptEngineering`, `ArtificialInteligence`,
  `ChatGPT`, `ClaudeAI`, `productivity`.
- **Blogs RSS**: One Useful Thing (Ethan Mollick), Simon Willison.
- **YouTube RSS**: PaulJames, JoaquinBarbera, PaulLipsky, AnjanaGowtham, AndyLok,
  BenAI92, AlejaviRivera, GraceLeung.

Editar `ia_scout.py` (constantes `REDDIT_SOURCES`, `RSS_BLOGS`, `YOUTUBE_CHANNELS`)
para añadir o quitar.
