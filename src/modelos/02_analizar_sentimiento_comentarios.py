"""Analiza la polaridad y percepción ciudadana de los comentarios limpios de Twitter sobre malla vial.

Utiliza el modelo RoBERTuito de pysentimiento ('pysentimiento/robertuito-sentiment-analysis') para clasificar el tono del comentario en:
- NEGATIVO (NEG): Denuncias, molestia, indignación o reclamo por huecos y estado vial.
- NEUTRO (NEU): Pregunta, constatación objetiva de ubicación o comentario informativo.
- POSITIVO (POS): Agradecimiento por reparación, obra completada o elogio.

Genera:
1. `data/twitter/modelos_twitter/comentarios_sentimiento.csv` y `.json`.
2. `data/twitter/modelos_twitter/resumen_percepcion_por_entidad.csv`: Desglose de percepción por entidad mencionada (@UMVBogota, @idubogota, @CarlosFGalan, @SectorMovilidad).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pysentimiento import create_analyzer

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("AnalisisSentimientoComentarios")

# Rutas del Proyecto
BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_CSV = BASE_DIR / "data" / "twitter" / "limpieza_twitter" / "comentarios_limpios.csv"
OUTPUT_DIR = BASE_DIR / "data" / "twitter" / "modelos_twitter"

OUTPUT_CSV = OUTPUT_DIR / "comentarios_sentimiento.csv"
OUTPUT_JSON = OUTPUT_DIR / "comentarios_sentimiento.json"
OUTPUT_RESUMEN_ENTIDADES = OUTPUT_DIR / "resumen_percepcion_por_entidad.csv"

MODELO_NOMBRE = "pysentimiento/robertuito-sentiment-analysis"

MAPA_ETIQUETAS = {
    "NEG": "NEGATIVO",
    "NEU": "NEUTRO",
    "POS": "POSITIVO",
}


def ejecutar_analisis_sentimiento() -> pd.DataFrame:
    """Ejecuta el análisis de sentimiento sobre los comentarios ciudadanos limpios."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not INPUT_CSV.exists():
        logger.error(f"No existe el archivo de entrada: {INPUT_CSV}")
        raise FileNotFoundError(f"Ejecuta primero 'src/scraping/04_limpiar_comentarios.py'. Archivo faltante: {INPUT_CSV}")

    df_limpio = pd.read_csv(INPUT_CSV)
    logger.info(f"Cargados {len(df_limpio)} comentarios limpios desde {INPUT_CSV}")

    # Filtrar comentarios candidatos viales o procesar todos los relevantes
    df_evaluar = df_limpio[df_limpio["es_candidato_vial"] == True].copy().reset_index(drop=True)
    logger.info(f"Comentarios relevantes a evaluar con RoBERTuito: {len(df_evaluar)}")

    if df_evaluar.empty:
        logger.warning("No hay comentarios marcados como relevantes para evaluar.")
        return pd.DataFrame()

    # Inicializar analizador de sentimiento de RoBERTuito en español
    logger.info(f"Cargando modelo de sentimiento: {MODELO_NOMBRE}...")
    analyzer = create_analyzer(task="sentiment", lang="es")

    resultados: list[dict[str, Any]] = []
    timestamp_analisis = datetime.now().astimezone().isoformat(timespec="seconds")

    for idx, row in enumerate(df_evaluar.itertuples(index=False), start=1):
        d_row = row._asdict()
        texto = str(d_row.get("texto_limpio", ""))

        if not texto:
            continue

        if idx % 25 == 0 or idx == len(df_evaluar):
            logger.info(f"Procesando comentario {idx}/{len(df_evaluar)}...")

        # Predicción de sentimiento
        pred = analyzer.predict(texto)

        codigo_sentimiento = str(pred.output)  # 'NEG', 'NEU', 'POS'
        etiqueta_sentimiento = MAPA_ETIQUETAS.get(codigo_sentimiento, codigo_sentimiento)
        probas = {k: round(float(v), 4) for k, v in pred.probas.items()}
        confianza = probas.get(codigo_sentimiento, 0.0)

        d_row["modelo_sentimiento"] = MODELO_NOMBRE
        d_row["sentimiento_codigo"] = codigo_sentimiento
        d_row["sentimiento_etiqueta"] = etiqueta_sentimiento
        d_row["confianza_sentimiento"] = confianza
        d_row["prob_negativo"] = probas.get("NEG", 0.0)
        d_row["prob_neutro"] = probas.get("NEU", 0.0)
        d_row["prob_positivo"] = probas.get("POS", 0.0)
        d_row["fecha_analisis_sentimiento"] = timestamp_analisis

        resultados.append(d_row)

    df_sentimiento = pd.DataFrame(resultados)

    # Resumen de polaridad general
    conteo_sentimiento = df_sentimiento["sentimiento_etiqueta"].value_counts()
    porcentajes = df_sentimiento["sentimiento_etiqueta"].value_counts(normalize=True).round(3) * 100

    logger.info("=" * 65)
    logger.info("RESUMEN GENERAL DE PERCEPCIÓN Y SENTIMIENTO CIUDADANO:")
    for etiq in ["NEGATIVO", "NEUTRO", "POSITIVO"]:
        c = conteo_sentimiento.get(etiq, 0)
        pct = porcentajes.get(etiq, 0.0)
        logger.info(f" - {etiq:10s}: {c:4d} comentarios ({pct:5.1f}%)")
    logger.info("=" * 65)

    # Desglose de percepción por entidad mencionada (@UMVBogota, @idubogota, @CarlosFGalan, @SectorMovilidad)
    resumen_entidades = []
    entidades_clave = ["@UMVBogota", "@idubogota", "@SectorMovilidad", "@CarlosFGalan", "@Bogota"]

    for ent in entidades_clave:
        # Filtrar comentarios que mencionen o respondan a la entidad
        mask = df_sentimiento["texto_limpio"].str.contains(re.escape(ent), case=False, na=False) | (
            df_sentimiento["responde_a_usuario"].str.contains(re.escape(ent), case=False, na=False)
        )
        sub_df = df_sentimiento[mask]
        if not sub_df.empty:
            t_ent = len(sub_df)
            neg_ent = (sub_df["sentimiento_etiqueta"] == "NEGATIVO").sum()
            neu_ent = (sub_df["sentimiento_etiqueta"] == "NEUTRO").sum()
            pos_ent = (sub_df["sentimiento_etiqueta"] == "POSITIVO").sum()
            resumen_entidades.append({
                "entidad": ent,
                "total_comentarios": t_ent,
                "negativos": neg_ent,
                "pct_negativos": round((neg_ent / t_ent) * 100, 1),
                "neutros": neu_ent,
                "pct_neutros": round((neu_ent / t_ent) * 100, 1),
                "positivos": pos_ent,
                "pct_positivos": round((pos_ent / t_ent) * 100, 1),
                "promedio_likes": round(sub_df["favoritos"].mean(), 2),
            })

    df_entidades = pd.DataFrame(resumen_entidades)
    if not df_entidades.empty:
        df_entidades.to_csv(OUTPUT_RESUMEN_ENTIDADES, index=False, encoding="utf-8-sig")
        logger.info(f"Resumen de percepción por entidad guardado en: {OUTPUT_RESUMEN_ENTIDADES}")

    # Guardar salidas principales en CSV (utf-8-sig) y JSON
    df_sentimiento.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    registros_dict = df_sentimiento.to_dict(orient="records")
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(registros_dict, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"Dataset de comentarios con sentimiento guardado en: {OUTPUT_CSV}")
    logger.info(f"Dataset JSON con sentimiento guardado en: {OUTPUT_JSON}")

    return df_sentimiento


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    logger.info("Iniciando análisis de sentimiento de comentarios con RoBERTuito...")
    try:
        df_sent = ejecutar_analisis_sentimiento()
        if isinstance(df_sent, pd.DataFrame) and not df_sent.empty:
            logger.info("\nMuestra de comentarios clasificados con RoBERTuito:")
            cols = ["id_registro", "autor_username", "sentimiento_etiqueta", "confianza_sentimiento", "texto_limpio"]
            sample_str = df_sent[cols].head(5).to_string(index=False)
            sys.stdout.buffer.write((sample_str + "\n").encode("utf-8", errors="replace"))
    except Exception as exc:
        logger.error(f"Error durante el análisis de sentimiento: {exc}")
