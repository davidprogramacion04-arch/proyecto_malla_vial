"""Añade sentimiento agregando fragmentos de noticias extraídas.

Conserva todos los campos existentes del JSON y CSV. El resultado representa el
tono textual detectado por el modelo, no una medida directa de opinión ciudadana.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from pysentimiento import create_analyzer


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data" / "noticias" / "scraping_noticias"
JSON_FILE = DATA_DIR / "noticias_contenido_candidatas.json"
CSV_FILE = DATA_DIR / "noticias_contenido_candidatas.csv"

MODELO_SENTIMIENTO = "pysentimiento/robertuito-sentiment-analysis"
MAX_CARACTERES_FRAGMENTO = 350


def dividir_en_fragmentos(texto: str, max_caracteres: int = MAX_CARACTERES_FRAGMENTO) -> list[str]:
    """Divide el texto por oraciones para no exceder la longitud del modelo."""
    oraciones = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", texto).strip())
    fragmentos: list[str] = []
    fragmento_actual = ""

    for oracion in oraciones:
        if not oracion:
            continue
        if len(oracion) > max_caracteres:
            palabras = oracion.split()
            partes = [
                " ".join(palabras[i : i + max_caracteres // 6])
                for i in range(0, len(palabras), max_caracteres // 6)
            ]
        else:
            partes = [oracion]

        for parte in partes:
            if fragmento_actual and len(fragmento_actual) + len(parte) + 1 > max_caracteres:
                fragmentos.append(fragmento_actual)
                fragmento_actual = parte
            else:
                fragmento_actual = f"{fragmento_actual} {parte}".strip()

    if fragmento_actual:
        fragmentos.append(fragmento_actual)
    return fragmentos


def analizar_texto(texto: str, analizador) -> dict[str, object]:
    """Promedia probabilidades por fragmento y retorna la clase más probable."""
    fragmentos = dividir_en_fragmentos(texto)
    probabilidades_acumuladas: defaultdict[str, float] = defaultdict(float)

    for fragmento in fragmentos:
        prediccion = analizador.predict(fragmento)
        for etiqueta, probabilidad in prediccion.probas.items():
            probabilidades_acumuladas[etiqueta] += float(probabilidad)

    probabilidades = {
        etiqueta: round(total / len(fragmentos), 6)
        for etiqueta, total in probabilidades_acumuladas.items()
    }
    sentimiento = max(probabilidades, key=probabilidades.get)
    return {
        "sentimiento_codigo": sentimiento,
        "confianza_sentimiento_codigo": probabilidades[sentimiento],
        "probabilidades_sentimiento_codigo": probabilidades,
        "fragmentos_analizados_codigo": len(fragmentos),
    }


def main() -> None:
    if not JSON_FILE.exists():
        raise FileNotFoundError(f"No existe el JSON de noticias: {JSON_FILE}")

    with JSON_FILE.open(encoding="utf-8") as archivo:
        noticias = json.load(archivo)

    analizador = create_analyzer(task="sentiment", lang="es")
    total_con_texto = sum(bool(noticia.get("texto_noticia")) for noticia in noticias)
    print(f"Noticias con texto para analizar: {total_con_texto}")

    for posicion, noticia in enumerate(noticias, start=1):
        texto = noticia.get("texto_noticia")
        noticia["modelo_sentimiento_codigo"] = MODELO_SENTIMIENTO
        noticia["fecha_analisis_sentimiento_codigo"] = datetime.now().astimezone().isoformat(timespec="seconds")

        if not texto or not str(texto).strip():
            noticia.update(
                {
                    "sentimiento_codigo": None,
                    "confianza_sentimiento_codigo": None,
                    "probabilidades_sentimiento_codigo": None,
                    "fragmentos_analizados_codigo": 0,
                    "estado_sentimiento_codigo": "sin_texto",
                    "error_sentimiento_codigo": None,
                }
            )
            continue

        print(f"[{posicion}/{len(noticias)}] {noticia.get('id_registro')}")
        try:
            noticia.update(analizar_texto(str(texto), analizador))
            noticia["estado_sentimiento_codigo"] = "analizado"
            noticia["error_sentimiento_codigo"] = None
        except Exception as error:
            noticia.update(
                {
                    "sentimiento_codigo": None,
                    "confianza_sentimiento_codigo": None,
                    "probabilidades_sentimiento_codigo": None,
                    "fragmentos_analizados_codigo": 0,
                    "estado_sentimiento_codigo": "error_analisis",
                    "error_sentimiento_codigo": str(error),
                }
            )

    with JSON_FILE.open("w", encoding="utf-8") as archivo:
        json.dump(noticias, archivo, ensure_ascii=False, indent=2, default=str)

    pd.DataFrame(noticias).to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    print(f"\nJSON actualizado: {JSON_FILE}")
    print(f"CSV actualizado: {CSV_FILE}")


if __name__ == "__main__":
    main()
