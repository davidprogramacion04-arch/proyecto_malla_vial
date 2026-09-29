# Instrucciones para Codex — Primer paso del scraping del proyecto Malla Vial Bogotá

## Contexto

Estamos desarrollando un proyecto de Ciencia de Datos sobre la malla vial de Bogotá. El proyecto integra potencialmente:

- Reportes ciudadanos / PQRS de la UMV.
- Intervenciones realizadas por la UMV.
- Datos de siniestralidad de SIMUR/Secretaría Distrital de Movilidad.
- Información de infraestructura vial / IDECA / IDU.
- Noticias relacionadas con huecos, baches, deterioro vial, pavimento y malla vial.
- Publicaciones de redes sociales y, cuando sea técnicamente y legalmente posible, sus comentarios.

El objetivo general es construir evidencia para caracterizar y posteriormente priorizar segmentos o zonas de la malla vial que requieran atención, combinando información de infraestructura, siniestralidad e información ciudadana.

IMPORTANTE:
- En esta etapa NO hacer análisis de sentimiento.
- En esta etapa NO descargar comentarios de redes sociales.
- NO afirmar causalidad entre deterioro vial y accidentes.
- Primero construir una base limpia de publicaciones/noticias candidatas.
- Google News RSS será solamente el mecanismo de descubrimiento, no la fuente original de la noticia.

---

# Objetivo inmediato

Implementar el PRIMER PASO del pipeline:

## Descubrimiento y recolección de noticias mediante Google News RSS

El resultado debe ser un CSV con noticias candidatas relacionadas con:

- huecos en Bogotá
- baches en Bogotá
- malla vial de Bogotá
- deterioro vial
- pavimento
- UMV
- Alcaldía de Bogotá y malla vial

Flujo:

Google News RSS
→ búsquedas por palabras clave
→ noticias descubiertas
→ CSV de candidatos
→ filtro de relevancia (futuro)
→ extracción de contenido original (futuro)
→ limpieza/deduplicación
→ análisis de sentimiento/tema
→ redes sociales y comentarios

---

# Estructura esperada

El proyecto principal se llama:

proyecto_malla_vial_bogota/

Estructura:

proyecto_malla_vial_bogota/
├── data/
│   ├── raw/
│   │   └── scraping/
│   ├── processed/
│   └── external/
├── src/
│   └── scraping/
│       ├── 01_descubrir_noticias.py
│       ├── 02_filtrar_noticias.py
│       └── 03_limpiar_noticias.py
└── notebooks/
    └── exploracion_scraping.ipynb

Por ahora SOLO implementar:

- data/raw/scraping/
- src/scraping/01_descubrir_noticias.py

No es necesario implementar todavía los scripts 02 y 03.

---

# Dependencias

Usar Python y:

- feedparser
- pandas
- requests
- beautifulsoup4
- trafilatura

Instalación:

pip install feedparser requests beautifulsoup4 trafilatura pandas

Si alguna dependencia ya existe, no reinstalar innecesariamente.

---

# Consultas iniciales

Usar inicialmente:

CONSULTAS = [
    '"huecos" Bogotá',
    '"baches" Bogotá',
    '"malla vial" Bogotá',
    '"deterioro vial" Bogotá',
    '"pavimento" Bogotá',
    '"UMV" Bogotá',
    '"malla vial" "Alcaldía de Bogotá"',
]

La lista debe quedar fácil de editar.

No añadir decenas de consultas todavía. Primero evaluar la calidad de los resultados.

---

# Google News RSS

Usar el endpoint RSS de Google News con:

hl=es-419
gl=CO
ceid=CO:es-419

Construir la URL a partir de la consulta, usando urllib.parse.quote.

No utilizar Selenium, Playwright ni automatización de navegador en esta primera etapa.

---

# Campos que queremos obtener

Cada resultado debe guardar como mínimo:

- id_registro
- titulo
- url
- fecha_publicacion
- resumen
- consulta
- fuente_descubrimiento
- fecha_scraping

Ejemplo:

id_registro: news_00001
titulo: "Bogotá anuncia nuevas obras para mejorar la malla vial..."
url: URL del resultado
fecha_publicacion: fecha proporcionada por RSS
resumen: resumen disponible en RSS
consulta: "malla vial" Bogotá
fuente_descubrimiento: "Google News RSS"
fecha_scraping: timestamp de ejecución

---

# MUY IMPORTANTE: fuente vs fuente de descubrimiento

NO asumir que:

fuente = Google News

Google News NO es necesariamente el medio que publicó la noticia.

Google News es solamente nuestro mecanismo de descubrimiento.

Por eso en esta primera etapa debemos guardar:

fuente_descubrimiento = "Google News RSS"

Pero NO inventar todavía el campo:

fuente

La fuente/medio original se identificará en una etapa posterior mediante la URL o extracción del contenido.

Ejemplo futuro:

fuente = "El Tiempo"
fuente_descubrimiento = "Google News RSS"

o:

fuente = "Bogotá.gov.co"
fuente_descubrimiento = "Google News RSS"

No inventar fuentes.

---

# Script esperado

Crear:

src/scraping/01_descubrir_noticias.py

Debe:

1. Importar dependencias.
2. Determinar BASE_DIR a partir de la ubicación del script.
3. Crear automáticamente data/raw/scraping/.
4. Definir las consultas.
5. Crear una función buscar_google_news(consulta, limite=100).
6. Construir la URL RSS.
7. Ejecutar feedparser.parse().
8. Extraer los campos disponibles.
9. Agregar resultados de todas las consultas.
10. Crear un DataFrame.
11. Eliminar duplicados utilizando la URL.
12. Generar id_registro secuencial.
13. Guardar data/raw/scraping/noticias_descubiertas.csv.
14. Mostrar en consola:
   - consulta procesada
   - cantidad de resultados por consulta
   - total bruto
   - total después de deduplicar
   - ubicación final
   - primeras filas

---

# Código base

La implementación puede seguir esta lógica:

from pathlib import Path
from urllib.parse import quote
from datetime import datetime

import feedparser
import pandas as pd

BASE_DIR = Path(__file__).resolve().parents[2]

OUTPUT_DIR = BASE_DIR / "data" / "raw" / "scraping"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "noticias_descubiertas.csv"

CONSULTAS = [
    '"huecos" Bogotá',
    '"baches" Bogotá',
    '"malla vial" Bogotá',
    '"deterioro vial" Bogotá',
    '"pavimento" Bogotá',
    '"UMV" Bogotá',
    '"malla vial" "Alcaldía de Bogotá"',
]

def buscar_google_news(consulta, limite=100):
    url = (
        "https://news.google.com/rss/search?"
        f"q={quote(consulta)}&hl=es-419&gl=CO&ceid=CO:es-419"
    )

    feed = feedparser.parse(url)

    resultados = []

    for entry in feed.entries[:limite]:
        resultados.append({
            "titulo": entry.get("title"),
            "url": entry.get("link"),
            "fecha_publicacion": entry.get("published"),
            "resumen": entry.get("summary"),
            "consulta": consulta,
            "fuente_descubrimiento": "Google News RSS",
            "fecha_scraping": datetime.now().isoformat()
        })

    return resultados

todos_los_resultados = []

for consulta in CONSULTAS:
    print(f"Buscando: {consulta}")
    resultados = buscar_google_news(consulta)
    print(f"Resultados encontrados: {len(resultados)}")
    todos_los_resultados.extend(resultados)

df = pd.DataFrame(todos_los_resultados)

print(f"\nTotal bruto: {len(df)}")

df = df.drop_duplicates(subset=["url"]).reset_index(drop=True)

print(f"Total después de deduplicar: {len(df)}")

df.insert(
    0,
    "id_registro",
    [f"news_{i:05d}" for i in range(1, len(df) + 1)]
)

df.to_csv(
    OUTPUT_FILE,
    index=False,
    encoding="utf-8-sig"
)

print(f"\nArchivo guardado en: {OUTPUT_FILE}")
print("\nPrimeros registros:")
print(df.head(10).to_string(index=False))

---

# Mejoras permitidas

Codex puede mejorar el código siempre que mantenga el objetivo de esta etapa.

## Manejo de errores

Si una consulta falla, no detener todo el proceso. Mostrar el error y continuar.

No ocultar silenciosamente los errores.

## Reproducibilidad

Mantener las consultas en una variable fácil de modificar.

No usar rutas absolutas de Windows.

Usar pathlib.

## Encoding

Guardar el CSV con:

encoding="utf-8-sig"

para facilitar su apertura en Excel.

---

# Qué NO debe hacer todavía

NO implementar todavía:

- análisis de sentimiento
- clasificación automática
- scraping de comentarios
- scraping de Instagram
- scraping de TikTok
- scraping de X
- Selenium
- Playwright
- login automático
- bypass de CAPTCHA
- bypass de restricciones de plataformas
- extracción masiva de contenido protegido
- generación de conclusiones sobre la malla vial
- modelos de machine learning
- NLP avanzado

Todo eso vendrá después.

---

# Segundo paso futuro

Una vez creado:

data/raw/scraping/noticias_descubiertas.csv

se revisará la calidad de los resultados.

El segundo paso será:

DESCUBRIMIENTO
→ FILTRO DE RELEVANCIA
→ NOTICIAS RELEVANTES

El filtro debe distinguir, por ejemplo:

RELEVANTE:
"Conductores denuncian huecos en la Avenida Boyacá"

NO RELEVANTE:
"El hueco fiscal de Bogotá aumenta..."

Esto es importante porque palabras como "hueco" pueden tener significados que no corresponden al problema vial.

Inicialmente se podrán utilizar:

CLAVES_HUECOS = [
    "hueco",
    "bache",
    "malla vial",
    "deterioro vial",
    "asfalto",
    "pavimento"
]

CONTEXTO_VIAL = [
    "calle",
    "carrera",
    "avenida",
    "Bogotá",
    "UMV",
    "IDU",
    "movilidad"
]

EXCLUSIONES = [
    "hueco fiscal"
]

Pero NO implementar este filtro en la primera etapa si no es necesario.

Primero observar los resultados reales del RSS.

---

# Estructura futura de los datos

La estructura final de noticias/social media planteada es aproximadamente:

id_registro
fuente
tipo_fuente
autor_cuenta
titulo
fecha
fecha_publicacion
url
contenido
tema_vial
sentimiento
objetivo_sentimiento
score_relevancia
patrones_deterioro
patrones_contexto
metodo_extraccion
fuente_descubrimiento
consulta

NO es necesario llenar todos estos campos ahora.

En la primera etapa solo deben existir los campos de descubrimiento disponibles.

---

# Principios metodológicos

El pipeline debe ser:

1. Descubrir.
2. Filtrar.
3. Extraer.
4. Limpiar.
5. Deduplicar.
6. Clasificar.
7. Analizar sentimiento.
8. Integrar con las demás fuentes.

No comenzar descargando grandes cantidades de comentarios o contenido de redes sociales antes de saber qué publicaciones son relevantes.

Además:

- Las publicaciones de redes sociales no representan necesariamente a toda la población de Bogotá.
- Conservar la fuente y el método de extracción.
- Distinguir entre sentimiento sobre el estado de la vía y sentimiento sobre la respuesta institucional.
- Respetar las condiciones de uso y las restricciones técnicas de cada plataforma.

---

# Resultado esperado

Al finalizar esta tarea Codex debe haber creado:

1. src/scraping/01_descubrir_noticias.py
2. data/raw/scraping/noticias_descubiertas.csv

Ejecutar desde la raíz del proyecto:

python src/scraping/01_descubrir_noticias.py

El script debe mostrar:

- número de resultados por consulta
- número total de resultados
- número de registros únicos
- ruta del CSV generado
- primeras filas del DataFrame

NO avanzar automáticamente al análisis de sentimiento ni al scraping de redes sociales.

Primero ejecutar esta etapa, revisar los resultados y luego continuar con el siguiente paso.
