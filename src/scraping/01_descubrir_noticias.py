"""Descubre noticias candidatas sobre malla vial de Bogotá mediante Google News RSS.

Esta etapa solo descubre metadatos publicados en el RSS. No descarga el artículo
original, no clasifica relevancia y no realiza análisis de sentimiento.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import feedparser
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "data" / "noticias" / "scraping_noticias"
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

COLUMNAS = [
    "id_registro",
    "titulo",
    "url",
    "fecha_publicacion",
    "resumen",
    "consulta",
    "fuente_descubrimiento",
    "fecha_scraping",
]


def buscar_google_news(consulta: str, limite: int = 100) -> list[dict[str, str | None]]:
    """Obtiene hasta ``limite`` entradas para una consulta de Google News RSS."""
    url_rss = (
        "https://news.google.com/rss/search?"
        f"q={quote(consulta)}&hl=es-419&gl=CO&ceid=CO:es-419"
    )
    feed = feedparser.parse(url_rss)

    if getattr(feed, "bozo", False):
        raise RuntimeError(f"Respuesta RSS no válida: {feed.bozo_exception}")

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return [
        {
            "titulo": entry.get("title"),
            "url": entry.get("link"),
            "fecha_publicacion": entry.get("published"),
            "resumen": entry.get("summary"),
            "consulta": consulta,
            "fuente_descubrimiento": "Google News RSS",
            "fecha_scraping": timestamp,
        }
        for entry in feed.entries[:limite]
    ]


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    todos_los_resultados: list[dict[str, str | None]] = []

    for consulta in CONSULTAS:
        print(f"Buscando: {consulta}")
        try:
            resultados = buscar_google_news(consulta)
        except Exception as error:  # Una consulta fallida no interrumpe las demás.
            print(f"Error al consultar {consulta!r}: {error}")
            continue

        print(f"Resultados encontrados: {len(resultados)}")
        todos_los_resultados.extend(resultados)

    df = pd.DataFrame(todos_los_resultados)
    if df.empty:
        df = pd.DataFrame(columns=COLUMNAS[1:])

    print(f"\nTotal bruto: {len(df)}")
    df = df.drop_duplicates(subset=["url"], keep="first").reset_index(drop=True)
    print(f"Total después de deduplicar: {len(df)}")

    df.insert(0, "id_registro", [f"news_{i:05d}" for i in range(1, len(df) + 1)])
    df = df.reindex(columns=COLUMNAS)
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print(f"\nArchivo guardado en: {OUTPUT_FILE}")
    print("\nPrimeros registros:")
    print(df.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
