"""Descubre y recolecta tweets y comentarios ciudadanos sobre la malla vial de Bogotá.

Basado en la arquitectura analizada en Scrapfly (2026):
- Búsqueda en X (x.com/search) con filtros booleanos, exclusiones y búsqueda directa de comentarios (filter:replies, to:entidad).
- Extracción profunda de hilos de conversación y comentarios ciudadanos (TweetDetail).
- Soporte para una sola cuenta verificada con cookies JSON autenticados.
- Detección automática de SCRAPFLY_API_KEY desde variables de entorno de Windows (HKCU/Environment).
- Medidor y limitador de créditos/tokens de Scrapfly para prevenir cobros o consumo excesivo de cuota.
- Almacenamiento segregado de comentarios ciudadanos para análisis directo de sentimiento y percepción.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import winreg
from datetime import datetime
from pathlib import Path
from typing import Any, Generator
from urllib.parse import quote

import pandas as pd
from dotenv import load_dotenv

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ScraperTwitterMallaVial")

# Rutas del Proyecto
BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "data" / "twitter" / "scraping_twitter"

OUTPUT_COMENTARIOS_CSV = OUTPUT_DIR / "comentarios_ciudadanos.csv"
OUTPUT_PRINCIPALES_CSV = OUTPUT_DIR / "tweets_principales.csv"
OUTPUT_COMPLETO_CSV = OUTPUT_DIR / "tweets_y_comentarios_completos.csv"
OUTPUT_COMPLETO_JSON = OUTPUT_DIR / "tweets_y_comentarios_completos.json"
OUTPUT_AUDITORIA = OUTPUT_DIR / "auditoria_consumo_scrapfly.json"

# Cargar variables de entorno desde .env
load_dotenv(BASE_DIR / ".env")

X_SELECTOR_FALLBACK = "[data-testid='primaryColumn'], [role='main'], main, body"

# =====================================================================
# Consultas de Búsqueda Especializadas
# =====================================================================

# 1. Búsquedas principales sobre el estado de la malla vial
CONSULTAS_PUBLICACIONES = [
    '("hueco" OR "huecos" OR "bache" OR "baches") (Bogotá OR Bogota) -fiscal -financiero -filter:retweets lang:es',
    '("malla vial" OR "deterioro vial" OR "pavimento" OR "asfalto") (Bogotá OR Bogota) -fiscal -filter:retweets lang:es',
    '(@UMVBogota OR @SectorMovilidad OR @idubogota) (hueco OR bache OR deterioro OR pavimento) -filter:retweets lang:es',
    '("huecos" OR "baches") (Bogotá OR Bogota) filter:images -fiscal -filter:retweets lang:es',
]

# 2. Búsquedas especializadas en comentarios y respuestas ciudadanas a entidades
CONSULTAS_COMENTARIOS_CIUDADANOS = [
    'to:UMVBogota (hueco OR bache OR daño OR calle OR avenida OR vía OR pavimentar OR arreglo OR cráter)',
    'to:idubogota (hueco OR bache OR cráter OR deterioro OR vía OR obras OR pavimento OR calle)',
    'to:SectorMovilidad (hueco OR bache OR accidente OR peligro OR moto OR ciclista OR cráter)',
    '("hueco" OR "bache" OR "malla vial") (Bogotá OR Bogota) filter:replies -fiscal lang:es',
]

COLUMNAS_SALIDA = [
    "id_registro",
    "tipo_registro",  # 'tweet_principal' o 'comentario'
    "tweet_id",
    "id_tweet_padre",
    "id_conversacion",
    "url",
    "autor_username",
    "autor_nombre",
    "autor_verificado",
    "texto",
    "fecha_publicacion",
    "idioma",
    "favoritos",
    "retweets",
    "respuestas",
    "citas",
    "vistas",
    "guardados",
    "tiene_multimedia",
    "urls_multimedia",
    "es_comentario",
    "responde_a_usuario",
    "consulta_busqueda",
    "fuente_descubrimiento",
    "fecha_scraping",
]


def obtener_scrapfly_key() -> str:
    """Obtiene la llave de Scrapfly desde .env o directamente del Registro de Windows (HKCU/Environment)."""
    key = os.getenv("SCRAPFLY_KEY", "").strip() or os.getenv("SCRAPFLY_API_KEY", "").strip()
    if key:
        return key

    # Intento de lectura desde HKCU\Environment
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
        val, _ = winreg.QueryValueEx(k, "SCRAPFLY_API_KEY")
        winreg.CloseKey(k)
        if val and str(val).strip():
            logger.info("Llave SCRAPFLY_API_KEY detectada automáticamente desde variables de usuario de Windows.")
            return str(val).strip()
    except Exception:
        pass

    return ""


def cargar_cookies_cuenta(archivo_json: Path | str) -> dict[str, str]:
    """Lee un archivo JSON de cookies exportadas del navegador y extrae el diccionario de cookies."""
    ruta = Path(archivo_json)
    if not ruta.is_absolute():
        ruta = BASE_DIR / ruta

    if not ruta.exists():
        logger.warning(f"Archivo de cookies no encontrado: {ruta}")
        return {}

    with ruta.open("r", encoding="utf-8") as f:
        data = json.load(f)

    cookies = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "name" in item and "value" in item:
                cookies[item["name"]] = item["value"]
    elif isinstance(data, dict):
        cookies = data

    return cookies


def obtener_credenciales_sesion() -> dict[str, str]:
    """Obtiene las cookies de una sola cuenta activa (JSON o .env)."""
    c1_path = os.getenv("TWITTER_COOKIES_FILE_1", "conversaciones/twitter_cookies_cuenta_1.json")
    cookies1 = cargar_cookies_cuenta(c1_path)
    if cookies1.get("auth_token") and cookies1.get("ct0"):
        logger.info(f"Cargadas cookies de la cuenta activa desde: {c1_path}")
        return cookies1

    auth_directo = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
    ct0_directo = os.getenv("TWITTER_CT0", "").strip()
    if auth_directo and ct0_directo:
        logger.info("Cargadas cookies directas desde variables TWITTER_AUTH_TOKEN y TWITTER_CT0.")
        return {"auth_token": auth_directo, "ct0": ct0_directo}

    raise ValueError("No se encontraron cookies válidas (auth_token y ct0) en el archivo JSON de la cuenta activa ni en .env.")


def validar_sesion_twitter(cookies: dict[str, str]) -> str | None:
    """Verifica si las cookies tienen una sesión activa en Twitter/X. Retorna el username o None."""
    import httpx

    bearer = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
    try:
        r = httpx.get(
            "https://x.com/i/api/1.1/account/settings.json",
            headers={
                "authorization": f"Bearer {bearer}",
                "x-csrf-token": cookies.get("ct0", ""),
                "cookie": cookie_str,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            },
            timeout=8.0,
        )
        if r.status_code == 200:
            return r.json().get("screen_name")
    except Exception:
        pass
    return None


class TwitterSearchQuery:
    """Constructor y formateador de filtros de búsqueda avanzada para X/Twitter."""

    def __init__(
        self,
        terminos: list[str],
        contexto: str = "Bogotá",
        exclusiones: list[str] | None = None,
        sin_retweets: bool = True,
        solo_con_imagenes: bool = False,
        solo_comentarios: bool = False,
        idioma: str = "es",
        desde_fecha: str | None = None,
        hasta_fecha: str | None = None,
        geocode: str | None = None,
    ):
        self.terminos = terminos
        self.contexto = contexto
        self.exclusiones = exclusiones or ["fiscal", "financiero", "presupuestal"]
        self.sin_retweets = sin_retweets
        self.solo_con_imagenes = solo_con_imagenes
        self.solo_comentarios = solo_comentarios
        self.idioma = idioma
        self.desde_fecha = desde_fecha
        self.hasta_fecha = hasta_fecha
        self.geocode = geocode

    def compilar(self) -> str:
        partes = []
        if self.terminos:
            terminos_fmt = [f'"{t}"' if " " in t else t for t in self.terminos]
            partes.append(f"({' OR '.join(terminos_fmt)})")

        if self.contexto:
            partes.append(f"({self.contexto})")

        for exc in self.exclusiones:
            partes.append(f"-{exc}")

        if self.idioma:
            partes.append(f"lang:{self.idioma}")

        if self.sin_retweets:
            partes.append("-filter:retweets")

        if self.solo_con_imagenes:
            partes.append("filter:images")

        if self.solo_comentarios:
            partes.append("filter:replies")

        if self.desde_fecha:
            partes.append(f"since:{self.desde_fecha}")
        if self.hasta_fecha:
            partes.append(f"until:{self.hasta_fecha}")

        if self.geocode:
            partes.append(f"geocode:{self.geocode}")

        return " ".join(partes)


def parsear_fecha_twitter(cadena_fecha: str | None) -> str | None:
    if not cadena_fecha:
        return None
    try:
        dt = datetime.strptime(cadena_fecha, "%a %b %d %H:%M:%S %z %Y")
        return dt.isoformat()
    except Exception:
        return cadena_fecha


def extraer_tweet_de_resultado(tweet_result: dict[str, Any], consulta_origen: str = "") -> dict[str, Any] | None:
    """Desempaqueta de forma segura un objeto Tweet de GraphQL (publicación o comentario)."""
    if not isinstance(tweet_result, dict):
        return None

    typename = tweet_result.get("__typename")
    if typename == "TweetWithVisibilityResults":
        tweet_data = tweet_result.get("tweet", {})
    elif typename == "Tweet":
        tweet_data = tweet_result
    else:
        tweet_data = tweet_result.get("tweet", tweet_result)

    legacy = tweet_data.get("legacy")
    if not legacy or not isinstance(legacy, dict):
        return None

    tweet_id = tweet_data.get("rest_id") or legacy.get("id_str")
    if not tweet_id:
        return None

    user_results = tweet_data.get("core", {}).get("user_results", {}).get("result", {})
    user_legacy = user_results.get("legacy", {})
    username = user_legacy.get("screen_name") or user_results.get("screen_name") or "desconocido"
    user_name = user_legacy.get("name") or user_results.get("name") or ""
    verified = bool(user_results.get("is_blue_verified") or user_legacy.get("verified"))

    texto = legacy.get("full_text") or legacy.get("text") or ""

    # Relación de comentarios / respuestas
    in_reply_to_status = legacy.get("in_reply_to_status_id_str")
    in_reply_to_user = legacy.get("in_reply_to_screen_name")
    conversation_id = legacy.get("conversation_id_str") or str(tweet_id)
    es_comentario = bool(in_reply_to_status)

    # Multimedia
    urls_multimedia = []
    extended_media = legacy.get("extended_entities", {}).get("media", [])
    if isinstance(extended_media, list):
        for med in extended_media:
            if isinstance(med, dict) and "media_url_https" in med:
                urls_multimedia.append(med["media_url_https"])

    # Métricas
    views_info = tweet_data.get("views", {})
    vistas_str = views_info.get("count") if isinstance(views_info, dict) else None
    vistas = int(vistas_str) if vistas_str and str(vistas_str).isdigit() else None

    return {
        "tipo_registro": "comentario" if es_comentario else "tweet_principal",
        "tweet_id": str(tweet_id),
        "id_tweet_padre": str(in_reply_to_status) if in_reply_to_status else None,
        "id_conversacion": str(conversation_id),
        "url": f"https://x.com/{username}/status/{tweet_id}",
        "autor_username": f"@{username}",
        "autor_nombre": user_name,
        "autor_verificado": verified,
        "texto": texto,
        "fecha_publicacion": parsear_fecha_twitter(legacy.get("created_at")),
        "idioma": legacy.get("lang"),
        "favoritos": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "respuestas": legacy.get("reply_count", 0),
        "citas": legacy.get("quote_count", 0),
        "vistas": vistas,
        "guardados": legacy.get("bookmark_count", 0),
        "tiene_multimedia": len(urls_multimedia) > 0,
        "urls_multimedia": urls_multimedia,
        "es_comentario": es_comentario,
        "responde_a_usuario": f"@{in_reply_to_user}" if in_reply_to_user else None,
        "consulta_busqueda": consulta_origen,
    }


def iterar_entradas_timeline(timeline_data: dict[str, Any], consulta_origen: str = "") -> Generator[dict[str, Any], None, None]:
    """Recorre las instrucciones de SearchTimeline o TweetDetail y extrae tweets y comentarios."""
    instructions = []
    # SearchTimeline
    search_timeline = (
        timeline_data.get("data", {})
        .get("search_by_raw_query", {})
        .get("search_timeline", {})
        .get("timeline", {})
    )
    # TweetDetail (conversaciones e hilos)
    tweet_detail = (
        timeline_data.get("data", {})
        .get("threaded_conversation_with_injections_v2", {})
    )

    if "instructions" in search_timeline:
        instructions = search_timeline["instructions"]
    elif "instructions" in tweet_detail:
        instructions = tweet_detail["instructions"]
    elif "instructions" in timeline_data.get("data", {}):
        instructions = timeline_data["data"]["instructions"]

    for instruction in instructions:
        if not isinstance(instruction, dict):
            continue

        entries = instruction.get("entries", [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            content = entry.get("content", {})
            entry_type = content.get("entryType")

            # Tweet individual o tweet focal
            if entry_type == "TimelineTimelineItem":
                item_content = content.get("itemContent", {})
                if item_content.get("itemType") == "TimelineTweet":
                    tweet_result = item_content.get("tweet_results", {}).get("result", {})
                    parsed = extraer_tweet_de_resultado(tweet_result, consulta_origen)
                    if parsed:
                        yield parsed

            # Hilo de conversación / comentarios anidados
            elif entry_type == "TimelineTimelineModule":
                items = content.get("items", [])
                for module_item in items:
                    sub_item_content = module_item.get("item", {}).get("itemContent", {})
                    if sub_item_content.get("itemType") == "TimelineTweet":
                        tweet_result = sub_item_content.get("tweet_results", {}).get("result", {})
                        parsed = extraer_tweet_de_resultado(tweet_result, consulta_origen)
                        if parsed:
                            yield parsed


class MedidorCreditosScrapfly:
    """Controla, monitorea y limita el consumo de créditos de la API de Scrapfly."""

    def __init__(self, limite_maximo: int = 50, costo_estimado_por_llamada: int = 5):
        self.limite_maximo = max(1, limite_maximo)
        self.costo_estimado_por_llamada = costo_estimado_por_llamada
        self.creditos_consumidos = 0
        self.solicitudes_realizadas = 0
        self.saldo_restante_cuenta: int | None = None
        self.historial_consumos: list[dict[str, Any]] = []

    def puede_realizar_solicitud(self) -> bool:
        if self.creditos_consumidos >= self.limite_maximo:
            logger.warning(
                f"[Medidor Scrapfly] Límite de seguridad alcanzado: "
                f"{self.creditos_consumidos}/{self.limite_maximo} créditos consumidos."
            )
            return False
        return True

    def registrar_respuesta(self, respuesta_scrapfly: Any) -> int:
        costo = getattr(respuesta_scrapfly, "cost", None)
        if costo is None:
            scrape_res = getattr(respuesta_scrapfly, "scrape_result", {}) or {}
            costo = scrape_res.get("cost", self.costo_estimado_por_llamada)

        costo_real = int(costo) if costo else self.costo_estimado_por_llamada
        self.creditos_consumidos += costo_real
        self.solicitudes_realizadas += 1

        saldo = getattr(respuesta_scrapfly, "remaining_quota", None)
        if saldo is not None:
            self.saldo_restante_cuenta = int(saldo)

        logger.info(
            f"[Medidor Scrapfly] Llamada exitosa | Costo: {costo_real} créditos | "
            f"Consumo sesión: {self.creditos_consumidos}/{self.limite_maximo} créditos"
            + (f" | Saldo cuenta: {self.saldo_restante_cuenta:,}" if self.saldo_restante_cuenta is not None else "")
        )

        self.historial_consumos.append({
            "solicitud_num": self.solicitudes_realizadas,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "costo_creditos": costo_real,
            "consumo_acumulado": self.creditos_consumidos,
            "limite_configurado": self.limite_maximo,
            "saldo_restante_cuenta": self.saldo_restante_cuenta,
        })

        if self.creditos_consumidos >= self.limite_maximo:
            logger.warning(
                f"[Medidor Scrapfly] ALERTA DE PRESUPUESTO: Se ha alcanzado el límite de {self.limite_maximo} créditos. "
                "Las siguientes solicitudes se cancelarán automáticamente para proteger tu saldo."
            )

        return costo_real

    def mostrar_resumen(self) -> None:
        logger.info("=" * 65)
        logger.info("RESUMEN DE CONSUMO DE CRÉDITOS SCRAPFLY:")
        logger.info(f" - Solicitudes ejecutadas: {self.solicitudes_realizadas}")
        logger.info(f" - Total créditos consumidos: {self.creditos_consumidos} créditos")
        logger.info(f" - Límite de seguridad establecido: {self.limite_maximo} créditos")
        if self.saldo_restante_cuenta is not None:
            logger.info(f" - Saldo restante en tu cuenta de Scrapfly: {self.saldo_restante_cuenta:,} créditos")
        logger.info("=" * 65)

    def guardar_auditoria(self, archivo_salida: Path) -> None:
        archivo_salida.parent.mkdir(parents=True, exist_ok=True)
        resumen = {
            "fecha_auditoria": datetime.now().astimezone().isoformat(timespec="seconds"),
            "total_solicitudes": self.solicitudes_realizadas,
            "total_creditos_consumidos": self.creditos_consumidos,
            "limite_seguridad": self.limite_maximo,
            "saldo_restante_cuenta": self.saldo_restante_cuenta,
            "historial": self.historial_consumos,
        }
        with archivo_salida.open("w", encoding="utf-8") as f:
            json.dump(resumen, f, ensure_ascii=False, indent=2)
        logger.info(f"[Medidor Scrapfly] Auditoría guardada en: {archivo_salida}")


class ScrapflyTwitterSearcher:
    """Motor de búsqueda y extracción de hilos/comentarios en X mediante Scrapfly API."""

    def __init__(
        self,
        scrapfly_key: str,
        cookies: dict[str, str],
        medidor: MedidorCreditosScrapfly | None = None,
    ):
        from scrapfly import ScrapflyClient

        self.client = ScrapflyClient(key=scrapfly_key)
        self.cookies = cookies
        self.medidor = medidor

    def _construir_cookie_header(self) -> str:
        return "; ".join([f"{k}={v}" for k, v in self.cookies.items()])

    def buscar(self, consulta: str) -> list[dict[str, Any]]:
        """Abre la búsqueda en x.com con sesión autenticada e intercepta la llamada SearchTimeline."""
        from scrapfly import ScrapeConfig

        if self.medidor and not self.medidor.puede_realizar_solicitud():
            logger.warning(f"[Scrapfly] Búsqueda omitida para '{consulta}': Límite de créditos alcanzado.")
            return []

        search_url = f"https://x.com/search?q={quote(consulta)}&f=live"
        logger.info(f"[Scrapfly] Navegando a búsqueda: {search_url}")

        config = ScrapeConfig(
            url=search_url,
            render_js=True,
            asp=True,
            session="twitter_malla_vial",
            session_sticky_proxy=True,
            cookies=self.cookies,
            headers={
                "x-csrf-token": self.cookies.get("ct0", ""),
            },
            wait_for_selector=X_SELECTOR_FALLBACK,
            rendering_wait=3000,
            raise_on_upstream_error=False,
            auto_scroll=True,
        )

        try:
            result = self.client.scrape(config)
            if self.medidor:
                self.medidor.registrar_respuesta(result)
        except Exception as err:
            logger.error(f"[Scrapfly] Error en búsqueda '{consulta}': {err}")
            return []

        url_final = result.scrape_result.get("url", "")
        if "onboarding/web" in url_final or "mode=login" in url_final:
            logger.warning(
                f"[Scrapfly] ALERTA DE SESIÓN: Twitter redirigió al inicio de sesión ({url_final[:80]}...). "
                "Las cookies de sesión (auth_token y ct0) han expirado o fueron cerradas en el navegador. "
                "Por favor inicia sesión en x.com en tu navegador y actualiza las cookies en .env o en los archivos JSON."
            )

        xhr_calls = result.scrape_result.get("browser_data", {}).get("xhr_call", [])
        tweets_encontrados: list[dict[str, Any]] = []

        for xhr in xhr_calls:
            url_xhr = xhr.get("url", "")
            if "SearchTimeline" in url_xhr and xhr.get("response"):
                try:
                    cuerpo = xhr["response"].get("body", "{}")
                    data = json.loads(cuerpo) if isinstance(cuerpo, str) else cuerpo
                    for item in iterar_entradas_timeline(data, consulta_origen=consulta):
                        tweets_encontrados.append(item)
                except Exception as err:
                    logger.warning(f"Error procesando SearchTimeline: {err}")

        logger.info(f"[Scrapfly] Registros parseados de la búsqueda: {len(tweets_encontrados)}")
        return tweets_encontrados

    def extraer_comentarios_hilo(self, tweet_url: str, tweet_id: str) -> list[dict[str, Any]]:
        """Navega a la URL del tweet e intercepta TweetDetail para extraer comentarios ciudadanos."""
        from scrapfly import ScrapeConfig

        if self.medidor and not self.medidor.puede_realizar_solicitud():
            logger.warning(f"[Scrapfly] Extracción de hilo omitida para {tweet_id}: Límite de créditos alcanzado.")
            return []

        logger.info(f"[Scrapfly] Extrayendo comentarios del hilo: {tweet_url}")
        config = ScrapeConfig(
            url=tweet_url,
            render_js=True,
            asp=True,
            session="twitter_malla_vial",
            session_sticky_proxy=True,
            cookies=self.cookies,
            headers={
                "x-csrf-token": self.cookies.get("ct0", ""),
            },
            wait_for_selector=X_SELECTOR_FALLBACK,
            rendering_wait=3000,
            raise_on_upstream_error=False,
            auto_scroll=True,
        )

        try:
            result = self.client.scrape(config)
            if self.medidor:
                self.medidor.registrar_respuesta(result)
        except Exception as err:
            logger.error(f"[Scrapfly] Error extrayendo hilo {tweet_url}: {err}")
            return []

        xhr_calls = result.scrape_result.get("browser_data", {}).get("xhr_call", [])
        comentarios_extraidos: list[dict[str, Any]] = []

        for xhr in xhr_calls:
            url_xhr = xhr.get("url", "")
            if "TweetDetail" in url_xhr and xhr.get("response"):
                try:
                    cuerpo = xhr["response"].get("body", "{}")
                    data = json.loads(cuerpo) if isinstance(cuerpo, str) else cuerpo
                    for item in iterar_entradas_timeline(data, consulta_origen="hilo_conversacion"):
                        if item["tweet_id"] != tweet_id:  # Excluir el tweet principal focal
                            item["tipo_registro"] = "comentario"
                            item["es_comentario"] = True
                            item["id_tweet_padre"] = tweet_id
                            comentarios_extraidos.append(item)
                except Exception as err:
                    logger.warning(f"Error procesando TweetDetail: {err}")

        logger.info(f"[Scrapfly] Comentarios encontrados en el hilo: {len(comentarios_extraidos)}")
        return comentarios_extraidos


class DirectSessionTwitterSearcher:
    """Motor de búsqueda directa contra los endpoints de X utilizando tokens de sesión (auth_token y ct0)."""

    BEARER_TOKEN = (
        "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
    )

    def __init__(self, cookies: dict[str, str]):
        import httpx

        self.cookies = cookies
        cookie_header = "; ".join([f"{k}={v}" for k, v in self.cookies.items()])
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "authorization": f"Bearer {self.BEARER_TOKEN}",
                "x-csrf-token": self.cookies.get("ct0", ""),
                "cookie": cookie_header,
                "x-twitter-active-user": "yes",
                "x-twitter-client-language": "es",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                ),
            },
        )

    def buscar(self, consulta: str) -> list[dict[str, Any]]:
        variables = {
            "rawQuery": consulta,
            "count": 20,
            "querySource": "typed_query",
            "product": "Latest",
        }
        features = {
            "rweb_tip_jar_status_details_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "unified_cards_ad_metadata_container_dynamic_card_content_query_enabled": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "responsive_web_enhance_cards_enabled": False,
        }

        url = (
            "https://x.com/i/api/graphql/gkjsKepM6gl_HmFWoWKfgg/SearchTimeline?"
            f"variables={quote(json.dumps(variables))}&features={quote(json.dumps(features))}"
        )

        logger.info(f"[Direct Session] Consultando SearchTimeline para: {consulta}")
        try:
            resp = self.client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                items = list(iterar_entradas_timeline(data, consulta_origen=consulta))
                logger.info(f"[Direct Session] Éxito: {len(items)} registros obtenidos.")
                return items
            elif resp.status_code == 403:
                logger.error("[Direct Session] Error 403: Verifica la validez de tus cookies de sesión.")
            else:
                logger.warning(f"[Direct Session] Código HTTP {resp.status_code}. Respuesta: {resp.text[:200]}")
        except Exception as err:
            logger.error(f"[Direct Session] Error en solicitud HTTP: {err}")

        return []

    def extraer_comentarios_hilo(self, tweet_url: str, tweet_id: str) -> list[dict[str, Any]]:
        """Extrae comentarios directamente mediante GraphQL TweetDetail."""
        variables = {
            "focalTweetId": tweet_id,
            "with_rux_injections": False,
            "includePromotedContent": False,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        features = {
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
        }

        url = (
            "https://x.com/i/api/graphql/VwfP3tfETx5YF9JcgdaoCw/TweetDetail?"
            f"variables={quote(json.dumps(variables))}&features={quote(json.dumps(features))}"
        )

        logger.info(f"[Direct Session] Consultando TweetDetail para comentarios del tweet {tweet_id}")
        try:
            resp = self.client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                comentarios = []
                for item in iterar_entradas_timeline(data, consulta_origen="hilo_conversacion"):
                    if item["tweet_id"] != tweet_id:
                        item["tipo_registro"] = "comentario"
                        item["es_comentario"] = True
                        item["id_tweet_padre"] = tweet_id
                        comentarios.append(item)
                logger.info(f"[Direct Session] Comentarios obtenidos del hilo: {len(comentarios)}")
                return comentarios
        except Exception as err:
            logger.error(f"[Direct Session] Error extrayendo comentarios: {err}")

        return []


def ejecutar_scraping_twitter(
    consultas: list[str] | None = None,
    extraer_hilos_comentarios: bool | None = None,
    usar_scrapfly_si_disponible: bool = True,
    limite_creditos_scrapfly: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Función principal: orquesta la búsqueda, extracción de comentarios, auditoría de cuota y guardado."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Cargar Cookies y Credenciales
    cookies_activas = obtener_credenciales_sesion()
    scrapfly_key = obtener_scrapfly_key()

    # Diagnóstico previo de sesión de Twitter
    usuario_activo = validar_sesion_twitter(cookies_activas)
    if usuario_activo:
        logger.info(f"Sesión de Twitter validada exitosamente para la cuenta: @{usuario_activo}")
    else:
        logger.warning(
            "[Atención Sesión X] Las cookies actuales no tienen una sesión activa o fueron invalidadas "
            "al cerrar sesión en el navegador. Si las búsquedas fallan por redirección a login, "
            "por favor abre x.com en tu navegador, inicia sesión y copia los valores frescos de auth_token y ct0 a .env."
        )

    # 2. Configurar Medidor de Créditos de Scrapfly
    if limite_creditos_scrapfly is None:
        env_limite = os.getenv("SCRAPFLY_MAX_CREDITOS", "50").strip()
        limite_creditos_scrapfly = int(env_limite) if env_limite.isdigit() else 50

    medidor = MedidorCreditosScrapfly(limite_maximo=limite_creditos_scrapfly)

    # 3. Selección de Motor
    sesion_valida = usuario_activo is not None
    motor = None
    nombre_motor = ""

    if not sesion_valida:
        logger.warning("\n" + "=" * 75)
        logger.warning("ATENCIÓN - COOKIES DE TWITTER EXPIRADAS O INVALIDADAS EN X.COM:")
        logger.warning("Twitter devolvió error de autenticación (401) con los tokens actuales.")
        logger.warning("Para corregirlo en 1 minuto:")
        logger.warning("  1. Abre https://x.com en tu navegador e inicia sesión activamente.")
        logger.warning("  2. Presiona F12 -> pestaña 'Application' ('Almacenamiento') -> Cookies -> https://x.com")
        logger.warning("  3. Copia el nuevo valor de 'auth_token' y 'ct0'.")
        logger.warning("  4. Actualízalos en tu archivo .env o en 'conversaciones/twitter_cookies_cuenta_1.json'.")
        logger.warning("=" * 75 + "\n")

    if scrapfly_key and usar_scrapfly_si_disponible:
        logger.info(f"Motor seleccionado: Scrapfly API (Límite máximo seguro: {medidor.limite_maximo} créditos)")
        motor = ScrapflyTwitterSearcher(
            scrapfly_key=scrapfly_key,
            cookies=cookies_activas,
            medidor=medidor,
        )
        nombre_motor = "Scrapfly"
    else:
        logger.info("Motor seleccionado: Conexión Directa con Sesión de Cuenta Verificada (HTTPX)")
        motor = DirectSessionTwitterSearcher(cookies=cookies_activas)
        nombre_motor = "Direct Session"

    # 4. Determinar lista de consultas (publicaciones + búsquedas directas de respuestas/comentarios)
    consultas_a_ejecutar = (
        consultas
        if consultas is not None
        else (CONSULTAS_PUBLICACIONES + CONSULTAS_COMENTARIOS_CIUDADANOS)
    )
    logger.info(f"Total de consultas con filtros a ejecutar: {len(consultas_a_ejecutar)}")

    todos_los_registros: list[dict[str, Any]] = []
    timestamp_scraping = datetime.now().astimezone().isoformat(timespec="seconds")

    # Fase 1: Búsqueda de publicaciones y comentarios directos
    for idx, q in enumerate(consultas_a_ejecutar, start=1):
        if scrapfly_key and usar_scrapfly_si_disponible and not medidor.puede_realizar_solicitud():
            logger.warning("[Presupuesto] Límite de créditos alcanzado. Deteniendo consultas de búsqueda...")
            break

        logger.info(f"\n[{idx}/{len(consultas_a_ejecutar)}] Ejecutando filtro: {q}")
        try:
            items = motor.buscar(q)
            for it in items:
                it["fuente_descubrimiento"] = f"{nombre_motor} Search"
                it["fecha_scraping"] = timestamp_scraping
            todos_los_registros.extend(items)
        except Exception as err:
            logger.error(f"Error procesando consulta '{q}': {err}")

        if idx < len(consultas_a_ejecutar):
            time.sleep(2.5)

    # Fase 2: Extracción profunda de hilos de comentarios para publicaciones con alta interacción
    if extraer_hilos_comentarios is None:
        extraer_hilos_comentarios = os.getenv("EXTRAER_COMENTARIOS_HILOS", "true").strip().lower() == "true"

    if extraer_hilos_comentarios and todos_los_registros:
        max_hilos = int(os.getenv("MAX_TWEETS_CON_COMENTARIOS", "15"))
        max_comentarios_por_hilo = int(os.getenv("MAX_COMENTARIOS_POR_HILO", "20"))
        # Seleccionamos tweets principales que reportaron respuestas > 0 ordenados por interacción
        candidatos_hilos = [
            t for t in todos_los_registros
            if t["tipo_registro"] == "tweet_principal" and t.get("respuestas", 0) > 0
        ]
        candidatos_hilos.sort(key=lambda x: x.get("respuestas", 0), reverse=True)
        hilos_a_procesar = candidatos_hilos[:max_hilos]

        logger.info(f"\n=== Fase 2: Extrayendo hasta {max_comentarios_por_hilo} comentarios por hilo en {len(hilos_a_procesar)} hilos principales ===")
        for idx, tweet_padre in enumerate(hilos_a_procesar, start=1):
            if scrapfly_key and usar_scrapfly_si_disponible and not medidor.puede_realizar_solicitud():
                logger.warning("[Presupuesto] Límite de créditos alcanzado. Deteniendo extracción de hilos...")
                break

            logger.info(f"[{idx}/{len(hilos_a_procesar)}] Hilo Tweet ID: {tweet_padre['tweet_id']} ({tweet_padre.get('respuestas', 0)} respuestas)")
            try:
                comentarios = motor.extraer_comentarios_hilo(tweet_padre["url"], tweet_padre["tweet_id"])
                comentarios_seleccionados = comentarios[:max_comentarios_por_hilo]
                for c in comentarios_seleccionados:
                    c["fuente_descubrimiento"] = f"{nombre_motor} ThreadDetail"
                    c["fecha_scraping"] = timestamp_scraping
                    c["consulta_busqueda"] = f"hilo:{tweet_padre['tweet_id']}"
                todos_los_registros.extend(comentarios_seleccionados)
                logger.info(f"   -> Añadidos {len(comentarios_seleccionados)} comentarios de este hilo.")
            except Exception as err:
                logger.error(f"Error extrayendo comentarios del tweet {tweet_padre['tweet_id']}: {err}")

            time.sleep(2.0)

    # Guardar auditoría de Scrapfly
    if scrapfly_key and usar_scrapfly_si_disponible and medidor.solicitudes_realizadas > 0:
        medidor.mostrar_resumen()
        medidor.guardar_auditoria(OUTPUT_AUDITORIA)

    if not todos_los_registros:
        logger.warning("No se obtuvieron tweets ni comentarios en esta ejecución.")
        df_vacio = pd.DataFrame(columns=COLUMNAS_SALIDA)
        return df_vacio, df_vacio

    # Deduplicar por tweet_id
    df_todos = pd.DataFrame(todos_los_registros)
    logger.info(f"\nTotal bruto capturado (tweets + comentarios): {len(df_todos)}")
    df_todos = df_todos.drop_duplicates(subset=["tweet_id"], keep="first").reset_index(drop=True)
    logger.info(f"Total tras deduplicar: {len(df_todos)}")

    # Asignar identificador secuencial
    df_todos.insert(0, "id_registro", [
        f"{'comment' if row.es_comentario else 'tweet'}_{i:05d}"
        for i, row in enumerate(df_todos.itertuples(), start=1)
    ])

    columnas_ordenadas = [c for c in COLUMNAS_SALIDA if c in df_todos.columns]
    df_todos = df_todos.reindex(columns=columnas_ordenadas)

    # Segregar datasets para análisis de percepción ciudadana
    df_comentarios = df_todos[df_todos["tipo_registro"] == "comentario"].copy().reset_index(drop=True)
    df_principales = df_todos[df_todos["tipo_registro"] == "tweet_principal"].copy().reset_index(drop=True)

    # Guardar en CSV (utf-8-sig para compatibilidad con Excel) y JSON
    df_todos.to_csv(OUTPUT_COMPLETO_CSV, index=False, encoding="utf-8-sig")
    df_comentarios.to_csv(OUTPUT_COMENTARIOS_CSV, index=False, encoding="utf-8-sig")
    df_principales.to_csv(OUTPUT_PRINCIPALES_CSV, index=False, encoding="utf-8-sig")

    registros_dict = df_todos.to_dict(orient="records")
    with OUTPUT_COMPLETO_JSON.open("w", encoding="utf-8") as f:
        json.dump(registros_dict, f, ensure_ascii=False, indent=2, default=str)

    logger.info("=" * 65)
    logger.info("ARCHIVOS GENERADOS EXITOSAMENTE:")
    logger.info(f" 1. Comentarios ciudadanos (Percepción): {OUTPUT_COMENTARIOS_CSV} ({len(df_comentarios)} comentarios)")
    logger.info(f" 2. Tweets principales (Denuncias/Obras): {OUTPUT_PRINCIPALES_CSV} ({len(df_principales)} tweets)")
    logger.info(f" 3. Base consolidada completa: {OUTPUT_COMPLETO_CSV} ({len(df_todos)} registros)")
    logger.info(f" 4. JSON estructurado completo: {OUTPUT_COMPLETO_JSON}")
    logger.info("=" * 65)

    return df_comentarios, df_principales


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    logger.info("Iniciando scraper de Twitter para Malla Vial Bogotá (Tweets y Comentarios Ciudadanos)...")
    try:
        df_comentarios, df_principales = ejecutar_scraping_twitter()
        if isinstance(df_comentarios, pd.DataFrame) and not df_comentarios.empty:
            logger.info("\nMuestra de Comentarios Ciudadanos recolectados:")
            cols_ver = [c for c in ["id_registro", "autor_username", "responde_a_usuario", "favoritos", "texto"] if c in df_comentarios.columns]
            sample_str = df_comentarios[cols_ver].head(5).to_string(index=False)
            sys.stdout.buffer.write((sample_str + "\n").encode("utf-8", errors="replace"))
    except Exception as exc:
        logger.error(f"Ejecución detenida: {exc}")
