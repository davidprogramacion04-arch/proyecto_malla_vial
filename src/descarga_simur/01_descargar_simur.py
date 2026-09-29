import requests
import pandas as pd
import time

# ------------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------------

URL = (
    "https://sig.simur.gov.co/arcgis/rest/services/"
    "Accidentalidad/WSAcidentalidad_TM/"
    "FeatureServer/0/query"
)

ANIOS = [2024, 2025, 2026]

# Tamaño del lote
BATCH_SIZE = 2000

# ------------------------------------------------------
# FUNCIÓN DE DESCARGA
# ------------------------------------------------------

def descargar_anio(anio):

    print(f"\nDescargando {anio}...")

    offset = 0
    todos = []

    while True:

        params = {
            "where": f"ANO_OCURRENCIA_ACC = {anio}",
            "outFields": (
                "OBJECTID,"
                "CIV,"
                "LOCALIDAD,"
                "BARRIO,"
                "MVINOMBRE,"
                "GRAVEDAD,"
                "CLASE_ACC,"
                "LATITUD,"
                "LONGITUD,"
                "FECHA_OCURRENCIA_ACC,"
                "PK_CALZADA"
            ),
            "returnGeometry": False,
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": BATCH_SIZE
        }

        response = requests.get(
            URL,
            params=params,
            timeout=60
        )

        response.raise_for_status()

        data = response.json()

        if "error" in data:
            print(data["error"])
            break

        features = data.get("features", [])

        if len(features) == 0:
            break

        registros = [
            f["attributes"]
            for f in features
        ]

        todos.extend(registros)

        print(
            f"Lote descargado: "
            f"{offset} -> {offset + len(registros)}"
        )

        offset += BATCH_SIZE

        time.sleep(1)

    df = pd.DataFrame(todos)

    return df

# ------------------------------------------------------
# DESCARGA TOTAL
# ------------------------------------------------------

dfs = []

for anio in ANIOS:

    df_anio = descargar_anio(anio)

    df_anio["ANIO_DESCARGA"] = anio

    dfs.append(df_anio)

# ------------------------------------------------------
# UNIR
# ------------------------------------------------------

df_total = pd.concat(
    dfs,
    ignore_index=True
)

# ------------------------------------------------------
# LIMPIAR CIV
# ------------------------------------------------------

df_total["CIV"] = (
    df_total["CIV"]
    .fillna(0)
    .astype(int)
    .astype(str)
)

# ------------------------------------------------------
# GUARDAR
# ------------------------------------------------------

# ------------------------------------------------------
# GUARDAR
# ------------------------------------------------------

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

df_total.to_parquet(
    DATA_DIR / "simur_2024_2026.parquet",
    index=False
)

df_total.to_csv(
    DATA_DIR / "simur_2024_2026.csv",
    index=False
)

print(f"\nArchivos guardados en:")
print(DATA_DIR)

# ------------------------------------------------------
# RESUMEN
# ------------------------------------------------------

print("\nDESCARGA FINALIZADA")
print(df_total.shape)

print("\nSiniestros por año:")
print(
    df_total
    .groupby("ANIO_DESCARGA")
    .size()
)

print("\nTop CIV:")
print(
    df_total
    .groupby("CIV")
    .size()
    .sort_values(ascending=False)
    .head(20)
)