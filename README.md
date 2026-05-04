# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA**.

Monitoriza Reddit, blogs RSS y canales de YouTube; deduplica entradas;
analiza cada novedad con Claude (Haiku 4.5); guarda los resultados en
Google Sheets y envía un resumen ordenado por Telegram.

## Estructura

```
ia_scout/
├── ia_scout.py          # Script principal
├── requirements.txt     # Dependencias Python
├── .env.example         # Plantilla de credenciales
├── .env                 # Credenciales reales (NO commitear)
├── credentials.json     # OAuth client de Google Cloud (NO commitear)
├── token.json           # Token OAuth generado en 1ª ejecución (NO commitear)
└── logs/scout.log       # Log de ejecuciones
```

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Editar .env con tus credenciales
```

## Credenciales Google Sheets

1. Crear proyecto en [Google Cloud Console](https://console.cloud.google.com).
2. Habilitar la API de Google Sheets.
3. Crear credenciales OAuth de tipo **Aplicación de escritorio**.
4. Descargar el JSON y guardarlo como `credentials.json` en la raíz del proyecto.
5. La primera ejecución abrirá el navegador para autorizar; el token queda
   guardado en `token.json` y las siguientes ejecuciones son silenciosas.

## Hojas requeridas en el Google Sheet

- **Hashes** — columnas: `content_hash | timestamp`
- **ScoutIA** — 15 columnas (ver `guardar_en_sheets` en `ia_scout.py`):
  `content_hash | fecha_detectado | fuente | titulo | url | autor | preview |
  keywords | notificado | vale | formato | puntuacion | gancho | angulo |
  estado`

## Ejecución

```bash
python ia_scout.py
```

## Programación con cron

Cada 6 horas:

```cron
0 */6 * * * cd /ruta/al/proyecto && /ruta/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Notas

- Se usa el algoritmo de hash base64 truncado para mantener compatibilidad
  con los hashes existentes generados desde n8n.
- Si una fuente Reddit falla (429, timeout) el ciclo continúa con las
  siguientes en lugar de abortar.
- Hay una pausa de 0,5 s entre llamadas a Claude para no saturar la API.
