"""Limpia, normaliza y filtra relevancia vial de los comentarios ciudadanos de Twitter.

Pipeline:
1. Lee `data/twitter/scraping_twitter/comentarios_ciudadanos.csv`.
2. Normaliza textos: limpia URLs superfluas, espacios múltiples y extrae menciones a entidades viales.
3. Estandariza fechas (año, mes, día de la semana, hora).
4. Aplica filtro de relevancia vial (palabras clave de deterioro vs exclusiones de hueco fiscal/política sin contexto vial).
5. Asigna `score_relevancia_vial` y bandera `es_candidato_vial`.
6. Deduplica comentarios y guarda en `data/twitter/limpieza_twitter/comentarios_limpios.csv` y `.json`.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("LimpiezaComentariosViales")

# Rutas del Proyecto
BASE_DIR = Path(__file__).resolve().parents[2]
INPUT_CSV = BASE_DIR / "data" / "twitter" / "scraping_twitter" / "comentarios_ciudadanos.csv"
OUTPUT_DIR = BASE_DIR / "data" / "twitter" / "limpieza_twitter"
OUTPUT_CSV = OUTPUT_DIR / "comentarios_limpios.csv"
OUTPUT_JSON = OUTPUT_DIR / "comentarios_limpios.json"

# =====================================================================
# Diccionarios Lexicográficos para Relevancia de Malla Vial
# =====================================================================

TERMINOS_DETERIORO_VIAL = [
    "hueco", "huecos", "bache", "baches", "malla vial", "deterioro vial",
    "pavimento", "asfalto", "cráter", "crater", "trampa mortal", "destruida",
    "daño vial", "desnivel", "alcantarilla destapada", "vía destruida",
    "calle destruida", "reparcheo", "mantenimiento vial"
]

CONTEXTO_URBANO_BOGOTA = [
    "bogotá", "bogota", "calle", "carrera", "avenida", "autopista", "ak", "kr",
    "cll", "cra", "av", "barrio", "localidad", "norte", "sur", "occidente",
    "oriental", "caracas", "boyacá", "boyaca", "suba", "usaquén", "usaquen",
    "engativá", "engativa", "kennedy", "bosa", "fontibón", "fontibon", "teusaquillo",
    "chapinero", "puente aranda", "tunjuelito", "usme", "san cristóbal", "umv",
    "idubogota", "idubogotá", "umvbogota", "umvbogotá", "sectormovilidad",
    "carlosfgalan", "alcaldia"
]

EXCLUSIONES_NO_VIALES = [
    "hueco fiscal", "hueco presupuestal", "hueco financiero", "hueco en la economía",
    "hueco en el bolsillo", "hueco emocional"
]


def limpiar_texto(texto: str | None) -> str:
    """Elimina URLs externas redundantes, normaliza espacios y conserva menciones/hashtags."""
    if not texto or not isinstance(texto, str):
        return ""

    # Reemplazar URLs opacas de Twitter/t.co por espacio
    txt = re.sub(r"https?://\S+", "", texto)

    # Eliminar retornos de carro y múltiples espacios
    txt = re.sub(r"\r\n|\r|\n|\t", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()

    return txt


def extraer_menciones(texto: str) -> list[str]:
    """Extrae la lista de usuarios o entidades mencionadas en el comentario (@entidad)."""
    if not texto:
        return []
    return re.findall(r"@\w+", texto)


def calcular_relevancia_vial(texto: str) -> tuple[bool, float, list[str], list[str]]:
    """Evalúa si un comentario trata legítimamente sobre deterioro vial de Bogotá.

    Returns:
        (es_candidato_vial, score_relevancia, palabras_deterioro_encontradas, contexto_encontrado)
    """
    txt_lower = texto.lower()

    # 1. Verificar si contiene exclusiones directas (ej. hueco fiscal)
    for exc in EXCLUSIONES_NO_VIALES:
        if exc in txt_lower:
            return False, 0.0, [], []

    # 2. Buscar términos de deterioro vial
    det_encontrados = [t for t in TERMINOS_DETERIORO_VIAL if re.search(r"\b" + re.escape(t) + r"\b", txt_lower)]

    # 3. Buscar términos de contexto urbano de Bogotá
    ctx_encontrados = [c for c in CONTEXTO_URBANO_BOGOTA if re.search(r"\b" + re.escape(c) + r"\b", txt_lower)]

    score = (len(det_encontrados) * 0.6) + (len(ctx_encontrados) * 0.4)

    # Es candidato si menciona al menos 1 término de deterioro o si menciona una entidad vial (@UMVBogota, @idubogota)
    menciones = extraer_menciones(texto)
    menciones_viales = [m for m in menciones if m.lower() in ["@umvbogota", "@idubogota", "@sectormovilidad", "@carlosfgalan"]]

    es_candidato = (len(det_encontrados) > 0) or (len(menciones_viales) > 0 and len(ctx_encontrados) > 0)

    return es_candidato, round(score, 2), det_encontrados, ctx_encontrados


def ejecutar_limpieza_comentarios() -> pd.DataFrame:
    """Función principal que procesa, limpia y filtra los comentarios ciudadanos."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not INPUT_CSV.exists():
        logger.error(f"No se encontró el archivo de entrada: {INPUT_CSV}")
        raise FileNotFoundError(f"Ejecuta primero 'src/scraping/03_descubrir_tweets.py'. Archivo faltante: {INPUT_CSV}")

    df_raw = pd.read_csv(INPUT_CSV)
    logger.info(f"Cargados {len(df_raw)} comentarios brutos desde {INPUT_CSV}")

    registros_limpios: list[dict[str, Any]] = []
    timestamp_procesamiento = datetime.now().astimezone().isoformat(timespec="seconds")

    for row in df_raw.itertuples(index=False):
        d_row = row._asdict()

        texto_original = str(d_row.get("texto", ""))
        texto_limpio = limpiar_texto(texto_original)

        if not texto_limpio:
            continue

        es_candidato, score_rel, det_mat, ctx_mat = calcular_relevancia_vial(texto_limpio)
        menciones = extraer_menciones(texto_limpio)

        # Parsear componentes de fecha
        f_pub = d_row.get("fecha_publicacion")
        año, mes, dia_semana, hora = None, None, None, None
        if f_pub and isinstance(f_pub, str):
            try:
                dt = datetime.fromisoformat(f_pub)
                año = dt.year
                mes = dt.strftime("%Y-%m")
                dia_semana = dt.strftime("%A")
                hora = dt.hour
            except Exception:
                pass

        registro = {
            "id_registro": d_row.get("id_registro"),
            "tipo_registro": d_row.get("tipo_registro", "comentario"),
            "tweet_id": str(d_row.get("tweet_id", "")),
            "id_tweet_padre": str(d_row.get("id_tweet_padre", "")) if pd.notna(d_row.get("id_tweet_padre")) else None,
            "id_conversacion": str(d_row.get("id_conversacion", "")) if pd.notna(d_row.get("id_conversacion")) else None,
            "url": d_row.get("url"),
            "autor_username": d_row.get("autor_username"),
            "autor_nombre": d_row.get("autor_nombre"),
            "autor_verificado": d_row.get("autor_verificado", False),
            "texto_original": texto_original,
            "texto_limpio": texto_limpio,
            "longitud_caracteres": len(texto_limpio),
            "menciones": menciones,
            "responde_a_usuario": d_row.get("responde_a_usuario"),
            "fecha_publicacion": f_pub,
            "año": año,
            "mes": mes,
            "dia_semana": dia_semana,
            "hora": hora,
            "idioma": d_row.get("idioma", "es"),
            "favoritos": int(d_row.get("favoritos", 0) or 0),
            "retweets": int(d_row.get("retweets", 0) or 0),
            "respuestas": int(d_row.get("respuestas", 0) or 0),
            "vistas": int(d_row.get("vistas", 0) or 0) if pd.notna(d_row.get("vistas")) else None,
            "tiene_multimedia": bool(d_row.get("tiene_multimedia", False)),
            "es_candidato_vial": es_candidato,
            "score_relevancia_vial": score_rel,
            "terminos_deterioro_detectados": det_mat,
            "contexto_urbano_detectado": ctx_mat,
            "consulta_busqueda": d_row.get("consulta_busqueda"),
            "fuente_descubrimiento": d_row.get("fuente_descubrimiento"),
            "fecha_limpieza": timestamp_procesamiento,
        }

        registros_limpios.append(registro)

    df_limpio = pd.DataFrame(registros_limpios)

    # Deduplicar comentarios por tweet_id
    df_limpio = df_limpio.drop_duplicates(subset=["tweet_id"], keep="first").reset_index(drop=True)

    # Filtrar candidatos viales relevantes
    candidatos = df_limpio[df_limpio["es_candidato_vial"] == True].copy().reset_index(drop=True)

    logger.info("=" * 65)
    logger.info(f"RESUMEN DE LIMPIEZA DE COMENTARIOS CIUDADANOS:")
    logger.info(f" - Comentarios totales procesados: {len(df_limpio)}")
    logger.info(f" - Comentarios clasificados como RELEVANTES VIALES: {len(candidatos)} ({round(len(candidatos)/max(1, len(df_limpio))*100, 1)}%)")
    logger.info(f" - Comentarios no viales o descartados (ruido): {len(df_limpio) - len(candidatos)}")
    logger.info("=" * 65)

    # Guardar salidas en CSV (utf-8-sig) y JSON
    df_limpio.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    registros_dict = df_limpio.to_dict(orient="records")
    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(registros_dict, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"Archivo CSV limpio guardado en: {OUTPUT_CSV}")
    logger.info(f"Archivo JSON limpio guardado en: {OUTPUT_JSON}")

    return df_limpio


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    logger.info("Iniciando pipeline de limpieza de comentarios ciudadanos...")
    try:
        df_res = ejecutar_limpieza_comentarios()
        if isinstance(df_res, pd.DataFrame) and not df_res.empty:
            logger.info("\nMuestra de comentarios limpios y evaluados:")
            cols = ["id_registro", "autor_username", "es_candidato_vial", "score_relevancia_vial", "texto_limpio"]
            sample_str = df_res[cols].head(5).to_string(index=False)
            sys.stdout.buffer.write((sample_str + "\n").encode("utf-8", errors="replace"))
    except Exception as exc:
        logger.error(f"Error durante la limpieza: {exc}")
