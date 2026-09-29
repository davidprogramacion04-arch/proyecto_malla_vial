"""Extrae contenido público de las noticias candidatas sobre malla vial.

Lee la salida del notebook de limpieza. No clasifica sentimiento: conserva el
puntaje de relevancia preliminar para facilitar la auditoría manual posterior.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import trafilatura
from googlenewsdecoder import gnewsdecoder


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "noticias" / "scraping_noticias"
INPUT_FILE = DATA_DIR / "noticias_limpias.csv"
OUTPUT_CSV = DATA_DIR / "noticias_contenido_candidatas.csv"
OUTPUT_JSON = DATA_DIR / "noticias_contenido_candidatas.json"

TIMEOUT_SEGUNDOS = 20
PAUSA_ENTRE_SOLICITUDES_SEGUNDOS = 1.5
USER_AGENT = "ProyectoMallaVialBogota/1.0 (investigacion academica)"
MAXIMO_SIN_TEXTO = 15


def es_candidata(valor: object) -> bool:
    """Convierte de forma segura el valor CSV de la bandera de relevancia."""
    return str(valor).strip().casefold() == "true"


def resolver_url_google_news(url_google_news: str) -> str:
    """Decodifica la URL opaca de Google News hacia la URL del medio original."""
    resultado = gnewsdecoder(
        url_google_news,
        interval=0.5,
        timeout=TIMEOUT_SEGUNDOS,
    )
    if not resultado.get("success"):
        raise RuntimeError(resultado.get("message", "No fue posible decodificar Google News."))
    return resultado["decoded_url"]


def extraer_noticia(session: requests.Session, url_google_news: str) -> tuple[str | None, str]:
    """Decodifica Google News y extrae texto público del medio original."""
    url_medio = resolver_url_google_news(url_google_news)
    respuesta = session.get(
        url_medio,
        timeout=TIMEOUT_SEGUNDOS,
        allow_redirects=True,
    )
    respuesta.raise_for_status()

    texto = trafilatura.extract(
        respuesta.text,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    return texto, respuesta.url


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"No existe el archivo de entrada: {INPUT_FILE}")

    df = pd.read_csv(INPUT_FILE)
    columna_filtro = "es_candidata_vial_preliminar"
    if columna_filtro not in df.columns:
        raise ValueError(
            f"Falta la columna {columna_filtro!r}. Ejecuta primero el notebook de limpieza."
        )

    candidatas = df[df[columna_filtro].map(es_candidata)].copy()
    print(f"Noticias candidatas a extraer: {len(candidatas)}")

    resultados: list[dict[str, object]] = []
    sin_texto_acumuladas = 0
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for posicion, noticia in enumerate(candidatas.itertuples(index=False), start=1):
        registro = noticia._asdict()
        print(f"[{posicion}/{len(candidatas)}] {registro['id_registro']}")

        resultado: dict[str, object] = {
            "id_registro": registro["id_registro"],
            "titulo": registro.get("titulo_limpio", registro.get("titulo")),
            "fecha_noticia": registro.get(
                "fecha_publicacion_estandarizada", registro.get("fecha_publicacion")
            ),
            "texto_noticia": None,
            "score_relevancia_preliminar": registro.get("score_relevancia_preliminar"),
            "url_google_news": registro["url"],
            "url_original": None,
            "estado_extraccion": "pendiente",
            "error_extraccion": None,
            "fecha_extraccion": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

        try:
            texto, url_original = extraer_noticia(session, registro["url"])
            resultado["url_original"] = url_original
            if texto:
                resultado["texto_noticia"] = texto
                resultado["estado_extraccion"] = "extraida"
            else:
                resultado["estado_extraccion"] = "sin_texto_extraible"
        except requests.RequestException as error:
            resultado["estado_extraccion"] = "error_solicitud"
            resultado["error_extraccion"] = str(error)
        except Exception as error:
            resultado["estado_extraccion"] = "error_extraccion"
            resultado["error_extraccion"] = str(error)

        resultados.append(resultado)

        if resultado["estado_extraccion"] != "extraida":
            sin_texto_acumuladas += 1

        if sin_texto_acumuladas > MAXIMO_SIN_TEXTO:
            print(
                f"Se detiene el proceso: se alcanzaron {sin_texto_acumuladas} "
                "noticias sin texto extraído."
            )
            break

        time.sleep(PAUSA_ENTRE_SOLICITUDES_SEGUNDOS)

    salida = pd.DataFrame(resultados)
    salida.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    with OUTPUT_JSON.open("w", encoding="utf-8") as archivo:
        json.dump(resultados, archivo, ensure_ascii=False, indent=2, default=str)

    print(f"\nCSV guardado en: {OUTPUT_CSV}")
    print(f"JSON guardado en: {OUTPUT_JSON}")
    print(salida["estado_extraccion"].value_counts(dropna=False).to_string())


if __name__ == "__main__":
    main()
