# =============================================================================
#  RIESGO CLIMÁTICO PROBABILÍSTICO — EL NIÑO 2026-2027 (PERÚ)
#  Herramienta de evaluación de amenaza de lluvias extremas para
#  infraestructura crítica (Hidroeléctricas, Saneamiento, Industria).
#
#  Arquitectura: 100% open-source, sin base de datos, sin API keys.
#    - Frontend      : Streamlit (tema corporativo azul marino)
#    - Geoespacial   : GeoPandas + Shapely + Plotly Mapbox (procesado en RAM)
#    - Amenaza       : Open-Meteo Seasonal API -> ECMWF SEAS5 (51 miembros)
#    - Climatología  : Open-Meteo Archive API  -> Reanálisis ERA5 (1991-2020)
#    - Reporte       : fpdf2 (PDF autocontenido, sin dependencias gráficas)
#
#  Ejecución local:
#    pip install streamlit geopandas shapely plotly requests pandas numpy fpdf2
#    streamlit run app.py
# =============================================================================

import io
import json
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd
import requests
import streamlit as st
import geopandas as gpd
from shapely.geometry import Point
import plotly.graph_objects as go
from fpdf import FPDF

# =============================================================================
# 1. CONFIGURACIÓN GENERAL Y TEMA VISUAL CORPORATIVO
# =============================================================================

st.set_page_config(
    page_title="Riesgo Climático El Niño 2026-2027 | Perú",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Paleta corporativa sobria: azules marinos profundos que denotan rigor técnico.
COLOR_FONDO = "#0B1D33"        # Azul marino casi negro (fondo principal)
COLOR_PANEL = "#12294A"        # Azul panel (tarjetas y sidebar)
COLOR_ACENTO = "#3FA7D6"       # Azul cian técnico (líneas y métricas)
COLOR_ALERTA = "#E4572E"       # Naranja rojizo (peligro crítico)
COLOR_ADVERTENCIA = "#F5B841"  # Ámbar (peligro moderado)
COLOR_OK = "#59C9A5"           # Verde azulado (condición normal)
COLOR_TEXTO = "#DCE7F5"        # Gris azulado claro (texto)

st.markdown(
    f"""
    <style>
      .stApp {{ background-color: {COLOR_FONDO}; color: {COLOR_TEXTO}; }}
      section[data-testid="stSidebar"] {{ background-color: {COLOR_PANEL}; }}
      h1, h2, h3, h4 {{ color: #FFFFFF !important; }}
      div[data-testid="stMetricValue"] {{ color: {COLOR_ACENTO}; }}
      .panel-enfen {{
          background-color: #1B3A5C; border-left: 6px solid {COLOR_ADVERTENCIA};
          padding: 14px 18px; border-radius: 6px; font-size: 0.92rem;
          line-height: 1.5; margin-bottom: 12px;
      }}
      .tarjeta-riesgo {{
          padding: 16px 20px; border-radius: 8px; margin-bottom: 10px;
          font-size: 0.95rem; line-height: 1.55;
      }}
      .riesgo-critico  {{ background-color: rgba(228, 87, 46, 0.15); border-left: 6px solid {COLOR_ALERTA}; }}
      .riesgo-alto     {{ background-color: rgba(245, 184, 65, 0.12); border-left: 6px solid {COLOR_ADVERTENCIA}; }}
      .riesgo-normal   {{ background-color: rgba(89, 201, 165, 0.10); border-left: 6px solid {COLOR_OK}; }}

      /* ---------- CORRECCIÓN DE CONTRASTE (legibilidad sobre fondo oscuro) ----------
         Si la app corre sin el tema oscuro de .streamlit/config.toml, Streamlit usa
         su tema claro por defecto y las etiquetas quedan gris-oscuro sobre azul
         marino (ilegibles). Estas reglas fuerzan texto claro en los elementos de
         interfaz, sin tocar el interior de los inputs (que tienen fondo blanco). */
      section[data-testid="stSidebar"] label p,
      section[data-testid="stSidebar"] div[data-testid="stWidgetLabel"] p,
      section[data-testid="stSidebar"] .stMarkdown p {{
          color: {COLOR_TEXTO} !important;
      }}
      div[data-testid="stCaptionContainer"] p,
      div[data-testid="stCaptionContainer"] {{
          color: #A9BCD4 !important;           /* captions y subtítulos */
      }}
      /* Etiqueta superior de st.metric (p.ej. "Departamento detectado").
         Streamlit ha cambiado el nodo interno entre versiones, así que se cubren
         todas las variantes conocidas para garantizar legibilidad. */
      div[data-testid="stMetricLabel"],
      div[data-testid="stMetricLabel"] *,
      div[data-testid="stMetricLabel"] p,
      div[data-testid="stMetricLabel"] div,
      label[data-testid="stMetricLabel"],
      label[data-testid="stMetricLabel"] * {{
          color: #B7C7DA !important;
          opacity: 1 !important;
      }}
      div[data-testid="stMetricValue"],
      div[data-testid="stMetricValue"] * {{
          color: {COLOR_ACENTO} !important;    /* valor de st.metric */
      }}
      button[data-baseweb="tab"] p {{
          color: {COLOR_TEXTO} !important;     /* títulos de pestañas no activas */
      }}
      .panel-enfen {{ color: #EAF2FB; }}
      details summary p {{ color: {COLOR_TEXTO} !important; }}  /* expander */
      .stAlert p {{ color: inherit; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# 2. CONSTANTES DEL DOMINIO (temporada crítica, regiones, endpoints)
# =============================================================================

# Meses restringidos estrictamente al evento crítico confirmado por el ENFEN.
# Formato interno: (etiqueta_visible, año, número_de_mes)
MESES_EVENTO = [
    ("Octubre 2026", 2026, 10),
    ("Noviembre 2026", 2026, 11),
    ("Diciembre 2026", 2026, 12),
    ("Enero 2027", 2027, 1),
    ("Febrero 2027", 2027, 2),
    ("Marzo 2027", 2027, 3),
    ("Abril 2027", 2027, 4),
]

SECTORES = [
    "Generación Hidroeléctrica",
    "Generación Termoeléctrica",
    "Generación Solar",
    "Generación Eólica",
    "Subestación",
    "Tramo de Línea de Transmisión",
    "Saneamiento/Tratamiento de Agua",
    "Infraestructura Industrial General",
]

# --- Parámetros de las grillas del mapa de calor de probabilidad de lluvia ---
# Nivel nacional: grilla gruesa (~1°) sobre todo el territorio peruano.
# Nivel regional: grilla fina (~0.5°) alrededor del departamento del activo.
# Cada punto de grilla implica consultar el ensamble SEAS5, por lo que las
# resoluciones se eligen como compromiso entre detalle y tiempo de carga
# (los resultados quedan cacheados por mes tras la primera consulta).
RES_GRILLA_NACIONAL = 1.0     # grados
RES_GRILLA_REGIONAL = 0.5     # grados
MARGEN_GRILLA_REGIONAL = 0.5  # margen (°) alrededor del departamento
TAMANO_LOTE_GRILLA = 20       # nº de puntos por llamada batched a la API

# Agrupación climatológica de departamentos (nombres normalizados sin tildes).
# Física subyacente: durante El Niño, las aguas cálidas del Pacífico oriental
# desplazan la convección hacia la costa norte peruana (lluvias torrenciales),
# mientras que el desplazamiento de la circulación de Walker tiende a suprimir
# la convección sobre el Altiplano y la sierra sur (déficit de precipitación).
COSTA_NORTE_INTERMEDIA = {
    "tumbes", "piura", "lambayeque", "la libertad",
    "ancash", "lima", "lima province", "callao", "ica",
}
SIERRA_SUR_ALTIPLANO = {
    "puno", "cusco", "arequipa", "apurimac", "huancavelica", "ayacucho",
}

# Fuentes de datos abiertas (sin API key)
URL_GEOJSON_PERU = (
    "https://github.com/wmgeolab/geoBoundaries/raw/90a1d52/"
    "releaseData/gbOpen/PER/ADM1/geoBoundaries-PER-ADM1.geojson"
)
URL_API_ESTACIONAL = "https://seasonal-api.open-meteo.com/v1/seasonal"
URL_API_HISTORICA = "https://archive-api.open-meteo.com/v1/archive"

UMBRAL_PROBABILIDAD_CRITICA = 55.0  # % de miembros sobre el percentil 80
PERCENTIL_EXTREMO = 80              # Definición operativa de "lluvia extrema"
RADIO_BUFFER_KM = 10.0              # Zona de operación local alrededor de la planta

# Umbral intermedio (didáctico) para clasificar la amenaza mensual en la Pestaña 2.
UMBRAL_PROBABILIDAD_VIGILANCIA = 40.0  # % — entre este valor y el crítico = vigilancia

# --- Identidad / autoría de la plataforma ---
EMPRESA = "Unleashing Power | Lima - Perú"
AUTOR_CONTACTO = "cesar.vega@unleashing-power.com"
VERSION_ESTADO = "Versión BETA — herramienta en desarrollo"

# Contexto oficial hardcodeado según especificación del proyecto.
# NOTA DE MANTENIMIENTO: actualizar este bloque con cada nuevo comunicado ENFEN.
TEXTO_ENFEN = (
    "<b>Contexto Oficial ENFEN (Comunicado N°12-2026):</b> "
    "Alerta de El Niño Costero activa. Probabilidades estimadas para el "
    "verano 2026-2027: Niño Costero en región 1+2 "
    "(<b>Fuerte 48% / Moderado 46%</b>), El Niño Global en región 3.4 "
    "(<b>Fuerte 44% / Moderado 36%</b>)."
)
TEXTO_ENFEN_PDF = (
    "Contexto Oficial ENFEN (Comunicado N 12-2026): Alerta de El Niño Costero "
    "activa. Probabilidades estimadas para el verano 2026-2027: Niño Costero en "
    "región 1+2 (Fuerte 48% / Moderado 46%), El Niño Global en región 3.4 "
    "(Fuerte 44% / Moderado 36%)."
)


def normalizar(texto: str) -> str:
    """Quita tildes y pasa a minúsculas para comparar nombres de departamentos
    de forma robusta ('Áncash' == 'Ancash', 'Apurímac' == 'Apurimac')."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower()


# =============================================================================
# 3. CAPA GEOESPACIAL — carga del país, detección regional y buffer local
# =============================================================================

@st.cache_data(show_spinner="Cargando límites departamentales del Perú (geoBoundaries)...")
def cargar_departamentos() -> gpd.GeoDataFrame:
    """
    Paso 1 (Nacional): descarga en memoria el GeoJSON oficial ADM1 del Perú.
    Se usa requests (sigue la redirección de GitHub LFS) y se construye el
    GeoDataFrame directamente desde el JSON, evitando escribir a disco.
    """
    respuesta = requests.get(URL_GEOJSON_PERU, timeout=60)
    respuesta.raise_for_status()
    datos = respuesta.json()
    gdf = gpd.GeoDataFrame.from_features(datos["features"], crs="EPSG:4326")

    # geoBoundaries usa 'shapeName'; se detecta defensivamente por si cambia.
    columna_nombre = next(
        (c for c in ("shapeName", "NOMBDEP", "name", "NAME_1") if c in gdf.columns),
        None,
    )
    if columna_nombre is None:
        raise ValueError("El GeoJSON no contiene una columna de nombre reconocible.")
    gdf = gdf.rename(columns={columna_nombre: "departamento"})
    gdf["dep_norm"] = gdf["departamento"].apply(normalizar)
    return gdf[["departamento", "dep_norm", "geometry"]]


def detectar_departamento(gdf: gpd.GeoDataFrame, lat: float, lon: float):
    """
    Paso 2 (Regional): intersección espacial punto-en-polígono.
    Matemática: para cada polígono departamental P se evalúa el predicado
    topológico P.contains(punto) (algoritmo ray-casting de Shapely/GEOS).
    Devuelve la fila del departamento o None si el punto cae fuera del Perú.
    """
    punto = Point(lon, lat)  # Shapely usa el orden (x=lon, y=lat)
    mascara = gdf.geometry.contains(punto)
    if mascara.any():
        return gdf[mascara].iloc[0]
    return None


def crear_buffer_operacion(lat: float, lon: float) -> gpd.GeoSeries:
    """
    Paso 3 (Local): buffer circular de 10 km alrededor de la central.
    Física/geometría: bufferizar en grados introduce distorsión (1° de longitud
    se acorta con el coseno de la latitud), por lo que se proyecta el punto a su
    zona UTM métrica local, se bufferiza en metros exactos y se reproyecta a
    WGS84 para dibujarlo en el mapa. Si pyproj fallara, se usa la aproximación
    de ~0.09° (~10 km en el Ecuador) indicada en la especificación.
    """
    serie = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326")
    try:
        crs_utm = serie.estimate_utm_crs()
        buffer_metrico = serie.to_crs(crs_utm).buffer(RADIO_BUFFER_KM * 1000)
        return buffer_metrico.to_crs("EPSG:4326")
    except Exception:
        return serie.buffer(0.09)


# -----------------------------------------------------------------------------
# 3.a GRILLAS DE PUNTOS PARA EL MAPA DE CALOR (probabilidad de lluvia)
# -----------------------------------------------------------------------------

def _union_territorio(gdf: gpd.GeoDataFrame):
    """Unión geométrica de todos los departamentos (compatibilidad de versiones)."""
    try:
        return gdf.geometry.union_all()      # GeoPandas >= 0.14
    except AttributeError:
        return gdf.geometry.unary_union      # Versiones anteriores


def generar_puntos_grilla_nacional(gdf: gpd.GeoDataFrame) -> list:
    """
    Grilla gruesa (~1°) de puntos DENTRO del territorio peruano.
    Método: se recorre la caja envolvente del país y se conserva cada punto
    cuya intersección punto-en-polígono con la unión departamental sea
    verdadera (con un pequeño buffer para no perder celdas costeras).
    """
    from shapely.prepared import prep
    union = _union_territorio(gdf).buffer(0.15)
    preparado = prep(union)
    minx, miny, maxx, maxy = union.bounds
    puntos = []
    for lat in np.arange(np.floor(miny) + 0.5, maxy, RES_GRILLA_NACIONAL):
        for lon in np.arange(np.floor(minx) + 0.5, maxx, RES_GRILLA_NACIONAL):
            if preparado.contains(Point(lon, lat)):
                puntos.append((round(float(lat), 3), round(float(lon), 3)))
    return puntos


def generar_puntos_grilla_regional(fila_dep) -> list:
    """
    Grilla fina (~0.5°) alrededor del departamento del activo: caja envolvente
    del polígono departamental expandida por un margen, filtrada al entorno
    del departamento (polígono con buffer) para no consultar puntos lejanos.
    """
    from shapely.prepared import prep
    geom = fila_dep.geometry.buffer(MARGEN_GRILLA_REGIONAL)
    preparado = prep(geom)
    minx, miny, maxx, maxy = geom.bounds
    puntos = []
    lat = miny + RES_GRILLA_REGIONAL / 2
    while lat < maxy:
        lon = minx + RES_GRILLA_REGIONAL / 2
        while lon < maxx:
            if preparado.contains(Point(lon, lat)):
                puntos.append((round(float(lat), 3), round(float(lon), 3)))
            lon += RES_GRILLA_REGIONAL
        lat += RES_GRILLA_REGIONAL
    return puntos


# -----------------------------------------------------------------------------
# 3.b MOTOR DE PROBABILIDAD SOBRE LA GRILLA (SEAS5 batched + caché)
# -----------------------------------------------------------------------------

def _lotes(secuencia, tamano):
    """Parte una lista en lotes de tamaño fijo (para llamadas batched a la API)."""
    for i in range(0, len(secuencia), tamano):
        yield secuencia[i:i + tamano]


def _como_lista(respuesta_json):
    """La API devuelve un dict para 1 ubicación y una lista para varias."""
    return respuesta_json if isinstance(respuesta_json, list) else [respuesta_json]


@st.cache_data(show_spinner=False)
def obtener_probabilidad_grilla(puntos: tuple, anio: int, mes: int) -> pd.DataFrame:
    """
    Para cada punto (lat, lon) calcula un ÍNDICE DE HÚMEDO/SECO centrado en 50
    a partir de la ANOMALÍA MENSUAL de precipitación de SEAS5:

        índice = 50 + 45 * tanh(1.2 * anomalía_relativa)
        anomalía_relativa = anom / climatología   (climatología = media - anom)

    Interpretación: 50 = igual a la normal climatológica; > 50 = más lluvioso
    de lo normal (señal húmeda, tonos cian); < 50 = más seco (tonos marrones).

    Se usa SOLO el bloque mensual (no diario) porque: (a) tiene mayor alcance
    de pronóstico —cubre meses que el diario ya no alcanza, como enero—, (b) es
    la mitad de llamadas HTTP (más rápido) y (c) es más robusto. La probabilidad
    de excedencia rigurosa contra el umbral P80 histórico vive en la Pestaña 2,
    calculada en el punto exacto del activo. La función queda cacheada por
    (grilla, año, mes); si un lote falla, se salta ese lote sin romper el resto.
    """
    registros = []
    for lote in _lotes(list(puntos), TAMANO_LOTE_GRILLA):
        lats = ",".join(f"{p[0]:.3f}" for p in lote)
        lons = ",".join(f"{p[1]:.3f}" for p in lote)
        params_m = {
            "latitude": lats, "longitude": lons,
            "monthly": "precipitation_mean,precipitation_anomaly",
            "models": "ecmwf_seas5", "timezone": "GMT",
            "forecast_days": 215,   # Fuerza el horizonte completo (~7 meses) para
                                    # que el dato mensual alcance enero/febrero y no
                                    # se corte en diciembre por el default del API.
        }
        try:
            rm = requests.get(URL_API_ESTACIONAL, params=params_m, timeout=120)
            rm.raise_for_status()
            datos_m = _como_lista(rm.json())
        except Exception:
            continue  # Un lote caído no invalida el mapa completo.

        for (lat_p, lon_p), loc_m in zip(lote, datos_m):
            try:
                indice = _indice_humedad_punto(loc_m, anio, mes)
            except Exception:
                indice = None
            if indice is not None:
                registros.append({"lat": lat_p, "lon": lon_p, "prob": indice})

    return pd.DataFrame(registros, columns=["lat", "lon", "prob"])


def _indice_humedad_punto(loc_m, anio, mes):
    """
    Índice húmedo/seco (0-100, 50 = normal) desde la anomalía mensual SEAS5.
    Devuelve None si el mes objetivo no está dentro del horizonte del modelo.
    """
    mensual = loc_m.get("monthly", {})
    t = pd.to_datetime(mensual.get("time", []))
    clave_media = next((k for k in mensual if "precipitation_mean" in k), None)
    clave_anom = next((k for k in mensual if "precipitation_anomaly" in k), None)
    if not clave_media or not clave_anom or len(t) == 0:
        return None
    mascara = (t.year == anio) & (t.month == mes)
    if not mascara.any():
        return None  # Mes fuera del horizonte de pronóstico mensual.
    idx = int(np.argmax(mascara))
    media = float(pd.to_numeric(pd.Series(mensual[clave_media]), errors="coerce").iloc[idx])
    anom = float(pd.to_numeric(pd.Series(mensual[clave_anom]), errors="coerce").iloc[idx])
    if not np.isfinite(media) or not np.isfinite(anom):
        return None
    climatologia = max(media - anom, 0.05)          # mm/día de referencia
    anomalia_rel = anom / climatologia               # fracción sobre lo normal
    # tanh mantiene el índice acotado y suave incluso ante anomalías extremas
    # en zonas muy secas (donde la anomalía relativa puede dispararse).
    indice = 50.0 + 45.0 * np.tanh(1.2 * anomalia_rel)
    return float(np.clip(indice, 3.0, 97.0))


def generar_grilla_prob_demo(puntos: list, mes: int, semilla: int) -> pd.DataFrame:
    """
    MODO DEMOSTRACIÓN: campo sintético de probabilidad coherente con la física
    del ENOS (máximo húmedo en la costa norte, señal seca en la sierra sur),
    modulado por el ciclo estacional del verano costero. NO usar para decisiones.
    """
    rng = np.random.default_rng(semilla)
    factor_mes = {10: 0.55, 11: 0.65, 12: 0.80, 1: 0.95, 2: 1.00, 3: 0.95, 4: 0.70}.get(mes, 0.6)
    registros = []
    for lat, lon in puntos:
        nucleo_humedo = 88.0 * np.exp(-(((lat + 5.5) ** 2) + ((lon + 80.3) ** 2)) / 18.0)
        nucleo_seco = 30.0 * np.exp(-(((lat + 15.0) ** 2) + ((lon + 71.0) ** 2)) / 20.0)
        prob = 50.0 + factor_mes * nucleo_humedo - factor_mes * nucleo_seco
        prob += float(rng.normal(0, 4))
        registros.append({"lat": lat, "lon": lon, "prob": float(np.clip(prob, 2, 98))})
    return pd.DataFrame(registros)


# -----------------------------------------------------------------------------
# 3.c CONSTRUCTORES DE MAPA — Nacional, Regional y Local
# -----------------------------------------------------------------------------

# Escala DIVERGENTE centrada en 50 (=normal climatológica). Debajo de 50 = más
# seco (marrones); en 50 = neutro; encima de 50 = más húmedo (azules/cian). Al
# estar centrada, una desviación pequeña (p. ej. 45 vs 55) ya se distingue.
ESCALA_CALOR = [[0.00, "#7A3F12"], [0.30, "#B5824A"], [0.45, "#9A8E7A"],
                [0.50, "#6E7B82"], [0.55, "#4E7EA6"], [0.70, "#2E86C1"],
                [1.00, "#5BD0F5"]]

# Resolución del MALLADO VISUAL sobre el que se interpola (independiente de la
# grilla de DATOS). Más fino = más suave, con costo solo de dibujo local (sin
# llamadas a la API). Se afina más en el zoom regional que en el nacional.
RES_DISPLAY_NACIONAL = 0.30   # celdas visuales a nivel país (~2000 celdas)
RES_DISPLAY_REGIONAL = 0.10   # celdas visuales a nivel departamento


def _interpolar_malla(df_heat: pd.DataFrame, mascara_geom, resolucion_vis: float):
    """
    Interpola la probabilidad de los pocos puntos de datos (df_heat) sobre una
    malla fina, recortada al territorio (mascara_geom). Devuelve (lats, lons, Z)
    donde Z es una matriz 2D con NaN fuera del territorio o del casco de datos.

    Usa scipy.griddata (lineal) si está disponible; si no, cae a una
    interpolación por distancia inversa ponderada (IDW) hecha solo con numpy,
    de modo que la app funciona aunque scipy no esté instalado.
    """
    from shapely.prepared import prep

    pts = df_heat[["lon", "lat"]].to_numpy(dtype=float)
    vals = df_heat["prob"].to_numpy(dtype=float)
    minx, miny, maxx, maxy = mascara_geom.bounds
    lons = np.arange(minx, maxx + resolucion_vis, resolucion_vis)
    lats = np.arange(miny, maxy + resolucion_vis, resolucion_vis)
    malla_lon, malla_lat = np.meshgrid(lons, lats)

    # --- Interpolación de valores ---
    try:
        from scipy.interpolate import griddata
        Z = griddata(pts, vals, (malla_lon, malla_lat), method="linear")
        # Rellena huecos exteriores al casco con el vecino más cercano.
        faltantes = np.isnan(Z)
        if faltantes.any():
            Zn = griddata(pts, vals, (malla_lon, malla_lat), method="nearest")
            Z[faltantes] = Zn[faltantes]
    except Exception:
        # Fallback IDW (solo numpy): P(x) = sum(w_i * v_i) / sum(w_i), w=1/d^2.
        Z = _idw_numpy(pts, vals, malla_lon, malla_lat)

    # --- Recorte al territorio (punto-en-polígono) ---
    preparado = prep(mascara_geom)
    for i in range(malla_lat.shape[0]):
        for j in range(malla_lat.shape[1]):
            if not preparado.contains(Point(malla_lon[i, j], malla_lat[i, j])):
                Z[i, j] = np.nan
    return lats, lons, Z


def _idw_numpy(pts, vals, malla_lon, malla_lat, potencia=2.0):
    """Interpolación por distancia inversa ponderada, 100% numpy (fallback)."""
    Z = np.empty(malla_lon.shape, dtype=float)
    for i in range(malla_lon.shape[0]):
        d2 = ((malla_lon[i][:, None] - pts[:, 0]) ** 2 +
              (malla_lat[i][:, None] - pts[:, 1]) ** 2)
        d2 = np.maximum(d2, 1e-9)
        w = 1.0 / d2 ** (potencia / 2.0)
        Z[i] = (w @ vals) / w.sum(axis=1)
    return Z


def _geojson_malla_fina(lats, lons, Z, res):
    """
    Construye el GeoJSON de celdas pequeñas (una por nodo válido de la malla
    interpolada) y la lista de valores z correspondiente. Cada celda se pinta
    por su PROBABILIDAD REAL interpolada, no por densidad de puntos.
    """
    mitad = res / 2.0
    features, valores = [], []
    idx = 0
    for i in range(Z.shape[0]):
        for j in range(Z.shape[1]):
            v = Z[i, j]
            if np.isnan(v):
                continue
            la, lo = float(lats[i]), float(lons[j])
            anillo = [[lo - mitad, la - mitad], [lo + mitad, la - mitad],
                      [lo + mitad, la + mitad], [lo - mitad, la + mitad],
                      [lo - mitad, la - mitad]]
            features.append({"type": "Feature", "id": idx,
                             "geometry": {"type": "Polygon", "coordinates": [anillo]},
                             "properties": {}})
            valores.append(float(v))
            idx += 1
    return {"type": "FeatureCollection", "features": features}, valores


def _capa_calor(fig, df_heat, mascara_geom, res_display, mostrar_escala):
    """
    Añade la capa de calor SUAVIZADA de probabilidad de lluvia: interpola los
    pocos puntos de datos sobre una malla fina y la dibuja como celdas pequeñas
    coloreadas por su valor real (Choroplethmapbox), lo que da un aspecto
    continuo pero con colores fieles a la probabilidad (0-100 %).
    """
    if df_heat is None or df_heat.empty or mascara_geom is None:
        return
    df_heat = df_heat.reset_index(drop=True)
    if len(df_heat) < 3:
        return  # Se necesitan al menos 3 puntos para interpolar una superficie.

    try:
        lats, lons, Z = _interpolar_malla(df_heat, mascara_geom, res_display)
    except Exception:
        return

    geojson_celdas, valores = _geojson_malla_fina(lats, lons, Z, res_display)
    if not valores:
        return

    fig.add_trace(go.Choroplethmapbox(
        geojson=geojson_celdas,
        locations=list(range(len(valores))),
        z=valores,
        zmin=0, zmax=100,
        colorscale=ESCALA_CALOR,
        marker_line_width=0,
        marker_opacity=0.6,
        showscale=mostrar_escala,
        colorbar=dict(title=dict(text="Señal lluvia<br>(50 = normal)",
                                 font=dict(color="#DCE7F5", size=11)),
                      tickfont=dict(color="#DCE7F5"), thickness=12, len=0.7),
        hovertemplate="Índice húmedo/seco: %{z:.0f} (50 = normal)<extra>SEAS5</extra>",
    ))


def _capa_bordes(fig, gdf):
    """Bordes departamentales sutiles sobre el mapa base."""
    fig.add_trace(go.Choroplethmapbox(
        geojson=json.loads(gdf.to_json()),
        locations=gdf.index,
        z=[0] * len(gdf),
        colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
        marker_line_color="#7FA8C9", marker_line_width=0.6,
        marker_opacity=0.06, showscale=False,
        text=gdf["departamento"],
        hovertemplate="<b>%{text}</b><extra></extra>",
    ))


def _capa_departamento(fig, gdf, fila_dep):
    """Resaltado ámbar del departamento del activo."""
    if fila_dep is None:
        return
    gdf_sel = gdf[gdf["dep_norm"] == fila_dep["dep_norm"]]
    fig.add_trace(go.Choroplethmapbox(
        geojson=json.loads(gdf_sel.to_json()),
        locations=gdf_sel.index,
        z=[1] * len(gdf_sel),
        colorscale=[[0, COLOR_ADVERTENCIA], [1, COLOR_ADVERTENCIA]],
        marker_line_color=COLOR_ADVERTENCIA, marker_line_width=3,
        marker_opacity=0.10, showscale=False,
        text=gdf_sel["departamento"],
        hovertemplate="<b>%{text}</b><extra>Departamento del activo</extra>",
    ))


def _capa_pin(fig, lat, lon, con_texto=True):
    """Marcador de la central."""
    fig.add_trace(go.Scattermapbox(
        lat=[lat], lon=[lon],
        mode="markers+text" if con_texto else "markers",
        marker=dict(size=14, color=COLOR_ALERTA),
        text=["  Central"] if con_texto else None,
        textposition="middle right",
        textfont=dict(color="#FFFFFF", size=12),
        hovertemplate=f"Lat: {lat:.5f}<br>Lon: {lon:.5f}<extra>Central</extra>",
    ))


def _layout_mapa(fig, centro, zoom, altura):
    fig.update_layout(
        mapbox=dict(style="carto-darkmatter", center=centro, zoom=zoom),
        margin=dict(l=0, r=0, t=0, b=0), height=altura,
        paper_bgcolor=COLOR_FONDO, showlegend=False,
    )
    return fig


def construir_mapa_nacional(gdf, df_heat, fila_dep, lat, lon):
    """NIVEL 1 — Todo el Perú como referencia nacional + mapa de calor suavizado."""
    fig = go.Figure()
    _capa_calor(fig, df_heat, _union_territorio(gdf), RES_DISPLAY_NACIONAL, mostrar_escala=True)
    _capa_bordes(fig, gdf)
    _capa_departamento(fig, gdf, fila_dep)
    if fila_dep is not None:
        _capa_pin(fig, lat, lon, con_texto=False)
    return _layout_mapa(fig, {"lat": -9.19, "lon": -75.02}, 3.9, 470)


def construir_mapa_regional(gdf, df_heat, fila_dep, lat, lon):
    """NIVEL 2 — Zoom al departamento del activo + mapa de calor suavizado."""
    fig = go.Figure()
    # La máscara de DISPLAY es el departamento EXACTO (sin margen): así el color
    # se recorta a la silueta del departamento y no desborda cubriendo todo el
    # encuadre. Los datos sí se interpolan desde puntos de un área algo mayor.
    if fila_dep is not None:
        mascara_reg = fila_dep.geometry
    else:
        mascara_reg = _union_territorio(gdf)
    _capa_calor(fig, df_heat, mascara_reg, RES_DISPLAY_REGIONAL, mostrar_escala=False)
    _capa_bordes(fig, gdf)
    _capa_departamento(fig, gdf, fila_dep)
    _capa_pin(fig, lat, lon)
    if fila_dep is not None:
        c = fila_dep.geometry.centroid
        centro = {"lat": float(c.y), "lon": float(c.x)}
    else:
        centro = {"lat": lat, "lon": lon}
    return _layout_mapa(fig, centro, 6.6, 470)


def _color_desde_indice(valor):
    """Traduce un índice 0-100 a un color RGBA de la escala ESCALA_CALOR."""
    if valor is None or not np.isfinite(valor):
        return "rgba(63, 167, 214, 0.20)", "#3FA7D6"  # neutro por defecto
    t = float(np.clip(valor, 0, 100)) / 100.0
    # Interpolación lineal entre los tramos definidos de ESCALA_CALOR.
    for k in range(len(ESCALA_CALOR) - 1):
        t0, c0 = ESCALA_CALOR[k]
        t1, c1 = ESCALA_CALOR[k + 1]
        if t0 <= t <= t1:
            f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            rgb = [int(int(c0[i:i+2], 16) + f * (int(c1[i:i+2], 16) - int(c0[i:i+2], 16)))
                   for i in (1, 3, 5)]
            hexc = "#{:02X}{:02X}{:02X}".format(*rgb)
            return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},0.45)", hexc
    return "rgba(63, 167, 214, 0.20)", "#3FA7D6"


def _indice_en_punto(df_heat, lat, lon):
    """Índice del punto de datos más cercano a la planta (o None si no hay datos)."""
    if df_heat is None or df_heat.empty:
        return None
    d2 = (df_heat["lat"] - lat) ** 2 + (df_heat["lon"] - lon) ** 2
    return float(df_heat.loc[d2.idxmin(), "prob"])


def construir_mapa_local(buffer_geo, lat, lon, indice_local=None):
    """
    NIVEL 3 — Zoom a la zona de operación (buffer de 10 km). El relleno del
    círculo se colorea según el índice de anomalía de lluvia del mes seleccionado
    en el punto de la planta, de modo que este mapa TAMBIÉN cambia mes a mes.
    """
    fig = go.Figure()
    relleno, borde = _color_desde_indice(indice_local)
    if buffer_geo is not None:
        anillo = np.array(buffer_geo.iloc[0].exterior.coords)
        etiqueta = (f"Zona de operación ({RADIO_BUFFER_KM:.0f} km) · índice "
                    f"{indice_local:.0f}" if indice_local is not None
                    else f"Zona de operación ({RADIO_BUFFER_KM:.0f} km)")
        fig.add_trace(go.Scattermapbox(
            lat=anillo[:, 1], lon=anillo[:, 0],
            mode="lines", fill="toself",
            fillcolor=relleno,
            line=dict(color=borde, width=2.5),
            name=etiqueta,
            hoverinfo="name",
        ))
    _capa_pin(fig, lat, lon)
    return _layout_mapa(fig, {"lat": lat, "lon": lon}, 10.2, 500)


# =============================================================================
# 4. MOTOR DE DATOS CLIMÁTICOS — ERA5 (normal climatológica) + SEAS5 (51 miembros)
# =============================================================================

@st.cache_data(show_spinner="Descargando reanálisis ERA5 (1991-2020) para la normal climatológica...")
def obtener_climatologia(lat: float, lon: float) -> pd.DataFrame:
    """
    Normal Climatológica: descarga 30 años de precipitación diaria del
    reanálisis ERA5 (Copernicus, vía Open-Meteo Archive API) y la agrega a
    totales mensuales. Para cada mes calendario m se obtiene:
      - normal_mm : media de los 30 totales mensuales (la "normal" OMM 1991-2020)
      - p80_mm    : percentil 80 empírico de esos 30 totales; es el umbral
                    operativo de "mes anormalmente lluvioso" (se excede solo
                    2 de cada 10 años en el clima de referencia).
    """
    parametros = {
        "latitude": lat,
        "longitude": lon,
        "start_date": "1991-01-01",
        "end_date": "2020-12-31",
        "daily": "precipitation_sum",
        "timezone": "auto",
    }
    r = requests.get(URL_API_HISTORICA, params=parametros, timeout=120)
    r.raise_for_status()
    datos = r.json()["daily"]

    df = pd.DataFrame(
        {"fecha": pd.to_datetime(datos["time"]),
         "pp": pd.to_numeric(pd.Series(datos["precipitation_sum"]), errors="coerce")}
    ).dropna()
    df["anio"] = df["fecha"].dt.year
    df["mes"] = df["fecha"].dt.month

    # Total mensual por (año, mes) -> distribución empírica de 30 valores por mes.
    mensual = df.groupby(["anio", "mes"])["pp"].sum().reset_index()
    resumen = (
        mensual.groupby("mes")["pp"]
        .agg(normal_mm="mean", p80_mm=lambda s: float(np.percentile(s, PERCENTIL_EXTREMO)))
        .reset_index()
    )
    return resumen


@st.cache_data(show_spinner="Consultando ensamble ECMWF SEAS5 (51 miembros) vía Open-Meteo...")
def obtener_pronostico_seas5(lat: float, lon: float):
    """
    Pronóstico probabilístico estacional. Se hacen dos consultas al endpoint
    oficial de Open-Meteo (datos abiertos del ECMWF desde octubre 2025):

    (a) daily=precipitation_sum, models=ecmwf_seas5  -> series diarias de los
        51 miembros del ensamble (cada miembro es una evolución físicamente
        plausible de la atmósfera con condiciones iniciales perturbadas).
        Se agregan a totales mensuales POR MIEMBRO: eso construye la
        distribución de probabilidad de la lluvia mensual futura.

    (b) monthly=precipitation_mean,precipitation_anomaly -> media del ensamble
        y anomalía respecto al clima del propio modelo (hindcasts), usada como
        señal de signo (húmedo/seco) robusta a sesgos sistemáticos.

    Devuelve (df_miembros_mensual, df_anomalias, aviso) donde:
      df_miembros_mensual: filas = (anio, mes, miembro, total_mm)
      df_anomalias:        filas = (anio, mes, anomalia_mm_dia, media_mm_dia)
    """
    aviso = None

    # ---- (a) Miembros individuales, resolución diaria ----
    params_diario = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "models": "ecmwf_seas5",
        "forecast_days": 215,   # Horizonte máximo SEAS5 (~7 meses)
        "timezone": "auto",
    }
    r = requests.get(URL_API_ESTACIONAL, params=params_diario, timeout=120)
    r.raise_for_status()
    diario = r.json().get("daily", {})

    fechas = pd.to_datetime(diario.get("time", []))
    # Parseo defensivo: las claves de miembro pueden ser 'precipitation_sum',
    # 'precipitation_sum_member01', ..., según la versión de la API.
    claves_miembro = [k for k in diario.keys() if k.startswith("precipitation_sum")]

    registros = []
    for i, clave in enumerate(sorted(claves_miembro)):
        serie = pd.to_numeric(pd.Series(diario[clave]), errors="coerce")
        temp = pd.DataFrame({"fecha": fechas, "pp": serie}).dropna()
        temp["anio"] = temp["fecha"].dt.year
        temp["mes"] = temp["fecha"].dt.month
        # Solo meses completos: se descartan meses truncados por el horizonte.
        dias_por_mes = temp.groupby(["anio", "mes"])["fecha"].count()
        totales = temp.groupby(["anio", "mes"])["pp"].sum()
        for (anio, mes), total in totales.items():
            dias_calendario = pd.Period(f"{anio}-{mes:02d}").days_in_month
            if dias_por_mes.loc[(anio, mes)] >= dias_calendario - 2:
                registros.append(
                    {"anio": anio, "mes": mes, "miembro": i, "total_mm": float(total)}
                )
    df_miembros = pd.DataFrame(registros)

    n_miembros = df_miembros["miembro"].nunique() if not df_miembros.empty else 0
    if n_miembros < 2:
        aviso = (
            "La API devolvió la media del ensamble en lugar de los 51 miembros "
            "individuales; la probabilidad se estimará con la dispersión mensual "
            "reportada por el modelo."
        )

    # ---- (b) Media y anomalía mensual del ensamble ----
    df_anom = pd.DataFrame()
    try:
        params_mensual = {
            "latitude": lat,
            "longitude": lon,
            "monthly": "precipitation_mean,precipitation_anomaly",
            "models": "ecmwf_seas5",
            "timezone": "auto",
        }
        r2 = requests.get(URL_API_ESTACIONAL, params=params_mensual, timeout=120)
        r2.raise_for_status()
        mensual = r2.json().get("monthly", {})
        t = pd.to_datetime(mensual.get("time", []))
        clave_media = next((k for k in mensual if "precipitation_mean" in k), None)
        clave_anom = next((k for k in mensual if "precipitation_anomaly" in k), None)
        if clave_media and clave_anom:
            df_anom = pd.DataFrame(
                {
                    "anio": t.year,
                    "mes": t.month,
                    "media_mm_dia": pd.to_numeric(pd.Series(mensual[clave_media]), errors="coerce"),
                    "anomalia_mm_dia": pd.to_numeric(pd.Series(mensual[clave_anom]), errors="coerce"),
                }
            ).dropna(subset=["media_mm_dia"])
    except Exception:
        pass  # La anomalía es complementaria; el análisis principal usa (a).

    return df_miembros, df_anom, aviso


def generar_ensamble_demo(climatologia: pd.DataFrame, semilla: int) -> pd.DataFrame:
    """
    MODO DEMOSTRACIÓN (sin conexión): ensamble sintético de 51 miembros.
    Cada miembro muestrea una distribución Gamma ajustada a la normal mensual
    (la Gamma es la distribución estándar en hidrología para lluvia mensual:
    positiva y con cola derecha). Se aplica un factor húmedo tipo El Niño para
    ilustrar el comportamiento de la interfaz. NO USAR PARA DECISIONES REALES.
    """
    rng = np.random.default_rng(semilla)
    registros = []
    for etiqueta, anio, mes in MESES_EVENTO:
        normal = max(float(climatologia.loc[climatologia["mes"] == mes, "normal_mm"].iloc[0]), 1.0)
        media_nino = normal * 1.8          # Sesgo húmedo ilustrativo
        forma = 2.2                        # Parámetro de forma (asimetría típica)
        escala = media_nino / forma
        for miembro in range(51):
            registros.append(
                {"anio": anio, "mes": mes, "miembro": miembro,
                 "total_mm": float(rng.gamma(forma, escala))}
            )
    return pd.DataFrame(registros)


def calcular_probabilidad_excedencia(df_miembros, climatologia, anio, mes):
    """
    Núcleo probabilístico. Sea X_k el total mensual pronosticado por el
    miembro k (k = 1..N) y u = P80 el percentil 80 de la climatología ERA5
    de ese mes calendario. La probabilidad de lluvia anormalmente extrema es
    la frecuencia relativa de excedencia dentro del ensamble:

        P(X > u) = ( #{ k : X_k > u } / N ) * 100

    Esto convierte el ensamble físico del ECMWF en una probabilidad calibrable,
    en lugar de un pronóstico determinista de un solo número.
    """
    umbral = float(climatologia.loc[climatologia["mes"] == mes, "p80_mm"].iloc[0])
    normal = float(climatologia.loc[climatologia["mes"] == mes, "normal_mm"].iloc[0])

    sel = df_miembros[(df_miembros["anio"] == anio) & (df_miembros["mes"] == mes)]
    if sel.empty:
        return None, umbral, normal, sel

    valores = sel["total_mm"].to_numpy()
    probabilidad = 100.0 * float(np.mean(valores > umbral))
    return probabilidad, umbral, normal, sel


# =============================================================================
# 5. MATRIZ DE RIESGOS Y CONSECUENCIAS OPERATIVAS (lógica paramétrica)
# =============================================================================

# Mensajes de consecuencia por sector para el escenario CRÍTICO de lluvias
# extremas en la Costa Norte/Intermedia. Cada texto sigue la lógica RCM:
# mecanismo físico de la amenaza -> modo de falla -> efecto sobre la función.
_CONSECUENCIAS_LLUVIA_COSTA = {
    "Generación Hidroeléctrica":
        "Alta probabilidad de huaicos y deslizamientos en laderas. Riesgo "
        "extremo de colmatación de la bocatoma por lodo y sedimentos. "
        "Desgaste abrasivo severo en rodetes de turbina.",
    "Generación Termoeléctrica":
        "Riesgo de inundación pluvial de fosas de bombas de captación y "
        "sótanos de casa de máquinas. Turbidez y sedimentos extremos en el "
        "agua de refrigeración de ciclo abierto (obstrucción de filtros e "
        "intercambiadores). Posible interrupción del suministro de combustible "
        "por pérdida de vías de acceso.",
    "Generación Solar":
        "Nubosidad convectiva persistente que reduce la irradiancia y la "
        "generación en el periodo crítico. Riesgo de inundación de zanjas de "
        "canalización, inversores y centros de transformación a nivel de "
        "suelo, y de socavación de hincados/estructuras por escorrentía y "
        "flujos de lodo.",
    "Generación Eólica":
        "Riesgo de erosión y socavación de cimentaciones de aerogeneradores "
        "por escorrentía concentrada y huaicos. Pérdida de caminos internos "
        "del parque (aislamiento de posiciones para mantenimiento) y mayor "
        "exposición a descargas atmosféricas durante tormentas convectivas.",
    "Subestación":
        "Riesgo crítico de inundación pluvial del patio de llaves: falla de "
        "aislamiento en equipos a nivel de suelo, ingreso de agua a canaletas "
        "de cables y sala de control, y contaminación de aisladores por "
        "salpicadura de lodo. Probabilidad alta de desconexión forzada para "
        "proteger transformadores de potencia.",
    "Tramo de Línea de Transmisión":
        "Riesgo de socavación y pérdida de estabilidad de fundaciones de "
        "torres en cruces de quebradas activadas por huaicos. Deslizamientos "
        "en la franja de servidumbre y pérdida de accesos para cuadrillas de "
        "mantenimiento, elevando el tiempo medio de reparación (MTTR) ante "
        "cualquier falla.",
    "Saneamiento/Tratamiento de Agua":
        "Incremento exponencial de la turbidez en captaciones superficiales. "
        "Colmatación inminente de desarenadores. Riesgo de corte forzado del "
        "servicio de potabilización para proteger filtros.",
}
_CONSECUENCIA_LLUVIA_GENERICA = (
    "Riesgo de inundación pluvial en patios de llaves, subestaciones "
    "eléctricas a nivel de suelo y sótanos. Probabilidad alta de "
    "aislamiento físico de la planta por pérdida de vías de acceso en el "
    f"buffer de {RADIO_BUFFER_KM:.0f} km."
)

# Mensajes por sector para el escenario de SEQUÍA en la Sierra Sur/Altiplano.
_CONSECUENCIAS_SEQUIA_SIERRA = {
    "Generación Hidroeléctrica":
        "Anomalía de precipitación negativa. Riesgo crítico de reducción "
        "drástica del caudal de diseño útil en embalses, afectando el "
        "despacho de energía en horas punta.",
    "Generación Termoeléctrica":
        "Anomalía de precipitación negativa. Riesgo de indisponibilidad de "
        "agua dulce para los sistemas de refrigeración; evaluar reducción de "
        "carga, recirculación interna y fuentes alternativas de agua.",
    "Generación Solar":
        "Condición seca prolongada: acumulación acelerada de polvo sobre los "
        "módulos (soiling) sin lavado natural por lluvia, con pérdida "
        "progresiva de rendimiento. Reforzar el plan de limpieza y el "
        "monitoreo del ratio de performance.",
    "Generación Eólica":
        "La sequía no compromete directamente la función del parque, pero el "
        "polvo en suspensión acelera la erosión de bordes de ataque de palas. "
        "Mantener vigilancia estacional estándar.",
    "Subestación":
        "Condición seca prolongada: acumulación de polvo sobre aisladores sin "
        "lavado natural, elevando el riesgo de flameo (flashover) ante "
        "neblinas o lloviznas ligeras. Programar lavado de aisladores.",
    "Tramo de Línea de Transmisión":
        "Condición seca prolongada: contaminación de aisladores por polvo y "
        "mayor riesgo de incendios de vegetación bajo la franja de "
        "servidumbre. Reforzar inspección de cadenas de aisladores y control "
        "de vegetación.",
}
_CONSECUENCIA_SEQUIA_GENERICA = (
    "Caída severa en los niveles de acuíferos y ríos de captación. "
    "Necesidad de activar planes de contingencia para agua de "
    "refrigeración e implementar sistemas de recirculación interna."
)


def evaluar_consecuencias(dep_norm, sector, probabilidad, anomalia_mm_dia):
    """
    Reglas condicionales región x sector x señal probabilística.
    Devuelve (nivel, titulo, mensaje) donde nivel in {critico, alto, normal}.
    """
    es_costa = dep_norm in COSTA_NORTE_INTERMEDIA
    es_sierra_sur = dep_norm in SIERRA_SUR_ALTIPLANO
    prob = probabilidad if probabilidad is not None else 0.0
    seca = anomalia_mm_dia is not None and anomalia_mm_dia < 0

    if es_costa and prob > UMBRAL_PROBABILIDAD_CRITICA:
        mensaje = _CONSECUENCIAS_LLUVIA_COSTA.get(sector, _CONSECUENCIA_LLUVIA_GENERICA)
        return ("critico",
                "Peligro Crítico — Lluvias Extremas (Costa Norte/Intermedia)",
                mensaje)

    if es_sierra_sur and seca:
        mensaje = _CONSECUENCIAS_SEQUIA_SIERRA.get(sector, _CONSECUENCIA_SEQUIA_GENERICA)
        return ("alto", "Peligro de Sequía — Sierra Sur / Altiplano", mensaje)

    if es_costa:
        return ("alto", "Vigilancia — Costa bajo Alerta ENFEN",
                f"La probabilidad de excedencia del percentil {PERCENTIL_EXTREMO} "
                f"({prob:.0f}%) aún no supera el umbral crítico del "
                f"{UMBRAL_PROBABILIDAD_CRITICA:.0f}%, pero la región permanece bajo "
                "alerta oficial de El Niño Costero. Mantener monitoreo mensual del "
                "ensamble SEAS5 (actualización cada día 5) y revisar planes de "
                "limpieza de drenajes, desarenadores y accesos.")

    return ("normal", "Condición dentro de rangos de planificación",
            "La señal probabilística del ensamble para esta región y mes no supera "
            "los umbrales de peligro definidos. Se recomienda mantener la vigilancia "
            "estacional estándar y re-evaluar con cada actualización mensual de SEAS5.")


# =============================================================================
# 6. GENERACIÓN DEL REPORTE PDF (fpdf2, gráfico dibujado nativamente)
# =============================================================================

def _latin1(texto: str) -> str:
    """fpdf2 con fuentes base usa Latin-1; se sanea cualquier carácter fuera de rango."""
    return texto.encode("latin-1", "replace").decode("latin-1")


def generar_pdf(contexto: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # --- Encabezado corporativo ---
    pdf.set_fill_color(11, 29, 51)
    pdf.rect(0, 0, 210, 30, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_xy(10, 8)
    pdf.cell(0, 8, _latin1("Reporte de Riesgo Climático Probabilístico"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(10)
    pdf.cell(0, 6, _latin1("Temporada El Niño 2026-2027 | ECMWF SEAS5 + ERA5 | Perú"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(36)
    pdf.set_text_color(20, 20, 20)

    # --- Datos del activo ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("1. Identificación del activo evaluado"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    filas = [
        ("Coordenadas de la central", f"Lat {contexto['lat']:.5f} / Lon {contexto['lon']:.5f}"),
        ("Departamento detectado (geoespacial)", contexto["departamento"]),
        ("Sector industrial", contexto["sector"]),
        ("Mes evaluado", contexto["mes_etiqueta"]),
        ("Radio de operación analizado", f"{RADIO_BUFFER_KM:.0f} km"),
        ("Fecha de emisión del reporte", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Modo de datos", contexto["modo_datos"]),
        ("Emitido por", EMPRESA),
        ("Contacto del autor", AUTOR_CONTACTO),
    ]
    for etiqueta, valor in filas:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(75, 6, _latin1(etiqueta + ":"))
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, new_x="LMARGIN", new_y="NEXT", text= _latin1(str(valor)))
    pdf.ln(2)

    # --- Resultado probabilístico con barra dibujada nativamente ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("2. Resultado probabilístico de amenaza (lluvia mensual)"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    prob = contexto["probabilidad"]
    pdf.multi_cell(0, 5.5, new_x="LMARGIN", new_y="NEXT", text= _latin1(
        f"Normal climatológica ERA5 (1991-2020) del mes: {contexto['normal']:.1f} mm. "
        f"Umbral de extremo (percentil {PERCENTIL_EXTREMO}): {contexto['umbral']:.1f} mm. "
        f"Probabilidad de excedencia según el ensamble de {contexto['n_miembros']} "
        f"miembros SEAS5: {prob:.1f}%."
    ))
    # Barra de probabilidad: fondo gris + relleno proporcional coloreado por nivel.
    x0, y0, ancho, alto = 12, pdf.get_y() + 2, 150, 9
    pdf.set_fill_color(225, 228, 233)
    pdf.rect(x0, y0, ancho, alto, "F")
    if prob > UMBRAL_PROBABILIDAD_CRITICA:
        pdf.set_fill_color(228, 87, 46)
    elif prob > 35:
        pdf.set_fill_color(245, 184, 65)
    else:
        pdf.set_fill_color(89, 201, 165)
    pdf.rect(x0, y0, ancho * max(min(prob, 100), 0) / 100.0, alto, "F")
    pdf.set_xy(x0 + ancho + 4, y0 + 1.5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, f"{prob:.1f}%", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(y0 + alto + 5)

    # --- Tabla mes a mes de la temporada crítica (clima vs señal probabilística) ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("3. Panorama mensual de la temporada crítica (Oct 2026 - Abr 2027)"), new_x="LMARGIN", new_y="NEXT")

    anchos = (48, 44, 48, 46)  # Mes | Normal | Umbral P80 | Probabilidad
    encabezados = ("Mes", "Normal ERA5 (mm)",
                   f"Umbral P{PERCENTIL_EXTREMO} (mm)", "Prob. excedencia (%)")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(18, 41, 74)
    pdf.set_text_color(255, 255, 255)
    for ancho, encabezado in zip(anchos, encabezados):
        pdf.cell(ancho, 7, _latin1(encabezado), border=1, align="C", fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    for i, fila_mes in enumerate(contexto.get("temporada", [])):
        # Filas alternadas para legibilidad (estilo zebra).
        pdf.set_fill_color(240, 244, 249) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(anchos[0], 6.5, _latin1(fila_mes["mes"]), border=1, fill=True)
        pdf.cell(anchos[1], 6.5, f"{fila_mes['normal']:.1f}", border=1, align="C", fill=True)
        pdf.cell(anchos[2], 6.5, f"{fila_mes['p80']:.1f}", border=1, align="C", fill=True)
        prob_mes = fila_mes["prob"]
        if prob_mes is None or pd.isna(prob_mes):
            pdf.set_text_color(120, 120, 120)
            texto_prob = "fuera de horizonte"
        else:
            # Semáforo textual: rojo crítico, ámbar vigilancia, verde normal.
            if prob_mes > UMBRAL_PROBABILIDAD_CRITICA:
                pdf.set_text_color(200, 60, 30)
            elif prob_mes > 35:
                pdf.set_text_color(180, 130, 20)
            else:
                pdf.set_text_color(30, 130, 95)
            texto_prob = f"{prob_mes:.1f}"
        pdf.cell(anchos[3], 6.5, _latin1(texto_prob), border=1, align="C", fill=True)
        pdf.ln()
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
        "Probabilidad = fracción de miembros del ensamble SEAS5 cuyo total mensual "
        f"supera el percentil {PERCENTIL_EXTREMO} del clima ERA5 1991-2020 en el punto del activo."
    ))
    pdf.ln(2)

    # --- Lectura mes a mes (misma narrativa que la app) ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 6, _latin1("Lectura mes a mes de la temporada:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for color, texto in narrar_temporada_pdf(contexto.get("temporada", [])):
        pdf.set_text_color(*color)
        pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_latin1("- " + texto))
    pdf.set_text_color(90, 90, 90)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
        f"Semáforo: CRÍTICA (>= {UMBRAL_PROBABILIDAD_CRITICA:.0f}%)  |  VIGILANCIA "
        f"({UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}-{UMBRAL_PROBABILIDAD_CRITICA:.0f}%)  |  "
        f"BAJA (< {UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}%)."
    ))
    pdf.set_text_color(20, 20, 20)
    pdf.ln(3)

    # --- Riesgos operativos ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("4. Consecuencias y riesgos operativos identificados"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.multi_cell(0, 5.5, new_x="LMARGIN", new_y="NEXT", text= _latin1(contexto["riesgo_titulo"]))
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5.5, new_x="LMARGIN", new_y="NEXT", text= _latin1(contexto["riesgo_mensaje"]))
    pdf.ln(2)

    # --- Contexto oficial ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("5. Contexto oficial de alerta"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 10)
    pdf.multi_cell(0, 5.5, new_x="LMARGIN", new_y="NEXT", text= _latin1(TEXTO_ENFEN_PDF))
    pdf.ln(2)

    # --- Referencias metodológicas ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("6. Sustento científico y fuentes de datos"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    referencias = [
        "ECMWF SEAS5: sistema de pronóstico estacional de 51 miembros (Johnson et al., 2019, "
        "Geosci. Model Dev. 12, 1087-1117). Acceso abierto vía Open-Meteo Seasonal API.",
        "ERA5 / Copernicus Climate Change Service (C3S): reanálisis global usado como normal "
        "climatológica 1991-2020 (estándar OMM). Acceso vía Open-Meteo Archive API.",
        "Marco de riesgo IPCC AR6 (CMIP6/SSP): riesgo = amenaza x exposición x vulnerabilidad.",
        "geoBoundaries (Runfola et al., 2020, PLoS ONE): límites administrativos ADM1 del Perú.",
        "ENFEN (Comisión Multisectorial): comunicados oficiales de alerta El Niño Costero.",
        f"Definición de extremo: excedencia del percentil {PERCENTIL_EXTREMO} de la distribución "
        "empírica mensual 1991-2020; probabilidad = fracción de miembros del ensamble que exceden "
        "dicho umbral.",
    ]
    for ref in referencias:
        pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text= _latin1("- " + ref))
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text= _latin1(
        "Nota: los pronósticos estacionales son probabilísticos por naturaleza y no bias-corregidos "
        "a escala local; deben interpretarse como orientación de anomalía de área (36 km) y "
        "complementarse con monitoreo oficial de SENAMHI/ENFEN antes de decisiones operativas."
    ))
    pdf.ln(2)
    pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text= _latin1(
        f"{EMPRESA}  |  Autor: {AUTOR_CONTACTO}  |  {VERSION_ESTADO}."
    ))

    salida = pdf.output()  # fpdf2 >= 2.5 devuelve bytearray
    return bytes(salida)


# =============================================================================
# 6.b NARRATIVA MES A MES (lectura didáctica del gráfico de la Pestaña 2)
# =============================================================================

def clasificar_amenaza_mensual(prob):
    """Traduce la probabilidad de excedencia de un mes a un nivel didáctico.

    Devuelve (icono, etiqueta, color) para uso en la explicación textual.
    """
    if prob is None or pd.isna(prob):
        return ("⚪", "sin dato", COLOR_TEXTO)
    if prob >= UMBRAL_PROBABILIDAD_CRITICA:
        return ("🔴", "crítico", COLOR_ALERTA)
    if prob >= UMBRAL_PROBABILIDAD_VIGILANCIA:
        return ("🟠", "vigilancia", COLOR_ADVERTENCIA)
    return ("🟢", "bajo", COLOR_OK)


def narrar_temporada(df_temp):
    """Construye, mes a mes, una explicación en lenguaje claro del gráfico de amenaza.

    Lee los valores reales de `df_temporada` (probabilidad, normal y umbral P80 de cada
    mes) y devuelve una lista de líneas listas para renderizar con st.markdown. La idea
    es que un lector no técnico entienda, mes por mes, qué está diciendo la curva.
    """
    lineas = []
    for fila in df_temp.itertuples(index=False):
        icono, _, _ = clasificar_amenaza_mensual(fila.prob)
        normal_txt = f"{fila.normal:.1f} mm" if pd.notna(fila.normal) else "s/d"
        p80_txt = f"{fila.p80:.1f} mm" if pd.notna(fila.p80) else "s/d"
        sin_dato = fila.prob is None or pd.isna(fila.prob)

        if sin_dato:
            lineas.append(
                f"{icono} **{fila.mes} — sin dato aún.** El mes todavía no entra en el "
                f"horizonte de pronóstico de SEAS5 (~7 meses); por ahora solo se muestra la "
                f"climatología de referencia (normal {normal_txt}, umbral extremo {p80_txt}). "
                "El valor probabilístico se habilitará conforme avance el calendario."
            )
            continue

        prob = float(fila.prob)
        if prob >= UMBRAL_PROBABILIDAD_CRITICA:
            veredicto = (
                f"**{prob:.0f}% de los 51 escenarios** del modelo prevén un mes más lluvioso "
                f"de lo normal, por encima del umbral crítico del "
                f"{UMBRAL_PROBABILIDAD_CRITICA:.0f}%. **Amenaza CRÍTICA:** es el tipo de mes "
                "capaz de gatillar inundaciones, huaicos o colmatación sobre el activo."
            )
        elif prob >= UMBRAL_PROBABILIDAD_VIGILANCIA:
            veredicto = (
                f"**{prob:.0f}% de los escenarios** apuntan a lluvia por encima de lo normal. "
                f"Todavía por debajo del umbral crítico ({UMBRAL_PROBABILIDAD_CRITICA:.0f}%), "
                "pero es un mes de **VIGILANCIA:** conviene seguir de cerca los comunicados de ENFEN."
            )
        else:
            veredicto = (
                f"Solo **{prob:.0f}% de los escenarios** superan el umbral de lluvia extrema. "
                "**Amenaza BAJA:** la mayor parte del ensamble se mantiene dentro de lo normal."
            )
        lineas.append(
            f"{icono} **{fila.mes} — {prob:.0f}%.** {veredicto} "
            f"_(normal {normal_txt}; umbral extremo P{PERCENTIL_EXTREMO} {p80_txt})_"
        )
    return lineas


def _nivel_amenaza_pdf(prob):
    """Nivel + color RGB para la narrativa mensual del PDF (sin emoji, Latin-1)."""
    if prob is None or pd.isna(prob):
        return ("SIN DATO", (120, 120, 120))
    if prob >= UMBRAL_PROBABILIDAD_CRITICA:
        return ("CRÍTICA", (200, 60, 30))
    if prob >= UMBRAL_PROBABILIDAD_VIGILANCIA:
        return ("VIGILANCIA", (180, 130, 20))
    return ("BAJA", (30, 130, 95))


def narrar_temporada_pdf(temporada):
    """Versión Latin-1 (sin markdown ni emoji) de la narrativa mes a mes para el PDF.

    Recibe la lista de dicts de contexto['temporada'] y devuelve tuplas
    (color_rgb, texto_plano) listas para renderizar con multi_cell. Es el equivalente
    impreso de narrar_temporada(), para que el reporte diga lo mismo que la pantalla.
    """
    bloques = []
    for fila in temporada:
        prob = fila.get("prob")
        normal = fila.get("normal")
        p80 = fila.get("p80")
        nivel, color = _nivel_amenaza_pdf(prob)
        normal_txt = f"{normal:.1f} mm" if (normal is not None and not pd.isna(normal)) else "s/d"
        p80_txt = f"{p80:.1f} mm" if (p80 is not None and not pd.isna(p80)) else "s/d"

        if nivel == "SIN DATO":
            texto = (
                f"{fila['mes']}: sin dato aún. El mes todavía no entra en el horizonte de "
                f"pronóstico de SEAS5 (~7 meses); por ahora solo se muestra la climatología de "
                f"referencia (normal {normal_txt}, umbral extremo {p80_txt})."
            )
        else:
            p = float(prob)
            if nivel == "CRÍTICA":
                cuerpo = (
                    f"{p:.0f}% de los 51 escenarios prevén un mes más lluvioso de lo normal, "
                    f"por encima del umbral crítico del {UMBRAL_PROBABILIDAD_CRITICA:.0f}%. "
                    "Amenaza CRÍTICA: mes capaz de gatillar inundaciones, huaicos o colmatación "
                    "sobre el activo."
                )
            elif nivel == "VIGILANCIA":
                cuerpo = (
                    f"{p:.0f}% de los escenarios apuntan a lluvia por encima de lo normal, aún "
                    f"por debajo del umbral crítico ({UMBRAL_PROBABILIDAD_CRITICA:.0f}%). Mes de "
                    "VIGILANCIA: conviene seguir de cerca los comunicados de ENFEN."
                )
            else:
                cuerpo = (
                    f"solo {p:.0f}% de los escenarios superan el umbral de lluvia extrema. "
                    "Amenaza BAJA: la mayor parte del ensamble se mantiene dentro de lo normal."
                )
            texto = (
                f"{fila['mes']} ({p:.0f}%): {cuerpo} "
                f"(normal {normal_txt}; umbral extremo P{PERCENTIL_EXTREMO} {p80_txt})."
            )
        bloques.append((color, texto))
    return bloques


# =============================================================================
# 7. INTERFAZ — BARRA LATERAL DE ENTRADAS
# =============================================================================

st.sidebar.title("⚙️ Parámetros del Activo")
st.sidebar.caption("Evaluación probabilística — Temporada ENFEN Oct 2026 – Abr 2027")

lat_usuario = st.sidebar.number_input(
    "Latitud de la planta", min_value=-18.5, max_value=0.1,
    value=-5.19449, step=0.0001, format="%.5f",
    help="Grados decimales WGS84. Ejemplo Piura: -5.19449",
)
lon_usuario = st.sidebar.number_input(
    "Longitud de la planta", min_value=-81.5, max_value=-68.5,
    value=-80.63282, step=0.0001, format="%.5f",
    help="Grados decimales WGS84. Ejemplo Piura: -80.63282",
)
sector_usuario = st.sidebar.selectbox("Sector industrial", SECTORES)
etiqueta_mes = st.sidebar.selectbox(
    "Mes de análisis (evento crítico ENFEN)", [m[0] for m in MESES_EVENTO]
)
_, anio_sel, mes_sel = next(m for m in MESES_EVENTO if m[0] == etiqueta_mes)

modo_demo = st.sidebar.toggle(
    "Modo demostración (datos sintéticos)", value=False,
    help="Genera un ensamble sintético de 51 miembros si no hay conexión a las APIs. "
         "Los resultados NO son válidos para decisiones reales.",
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    f"<div class='panel-enfen'>{TEXTO_ENFEN}</div>", unsafe_allow_html=True
)

# =============================================================================
# 8. ORQUESTACIÓN PRINCIPAL
# =============================================================================

st.title("🌊 Plataforma de Riesgo Climático — El Niño 2026-2027")
st.caption(
    "Amenaza probabilística de lluvias extremas para infraestructura crítica en el Perú | "
    "ECMWF SEAS5 (51 miembros) · ERA5 · geoBoundaries · IPCC AR6"
)
st.caption(
    f"Desarrollado por **{EMPRESA}**  ·  Autor: {AUTOR_CONTACTO}  ·  _{VERSION_ESTADO}_"
)

# ---- Geoespacial ----
error_geo = None
fila_dep = None
buffer_geo = None
try:
    gdf_peru = cargar_departamentos()
    fila_dep = detectar_departamento(gdf_peru, lat_usuario, lon_usuario)
    buffer_geo = crear_buffer_operacion(lat_usuario, lon_usuario)
except Exception as e:
    error_geo = str(e)
    gdf_peru = None

if error_geo:
    st.error(
        "No se pudieron cargar los límites departamentales (geoBoundaries). "
        f"Verifica tu conexión a internet. Detalle técnico: {error_geo}"
    )
    st.stop()

if fila_dep is None:
    st.warning(
        "⚠️ Las coordenadas ingresadas no intersectan ningún departamento del Perú. "
        "Corrige la latitud/longitud en la barra lateral para continuar con el análisis."
    )
dep_nombre = fila_dep["departamento"] if fila_dep is not None else "—"
dep_norm = fila_dep["dep_norm"] if fila_dep is not None else ""

# ---- Motor climático ----
modo_datos = "OPERATIVO — APIs en vivo (Open-Meteo / ECMWF / ERA5)"
aviso_ensamble = None
climatologia = None
df_miembros = pd.DataFrame()
df_anom = pd.DataFrame()

try:
    climatologia = obtener_climatologia(lat_usuario, lon_usuario)
except Exception as e:
    st.warning(f"No fue posible descargar la climatología ERA5 ({e}). Se usará una "
               "climatología sintética de demostración.")
    # Climatología de respaldo mínima para que la interfaz siga operativa.
    climatologia = pd.DataFrame({
        "mes": range(1, 13),
        "normal_mm": [80, 95, 90, 45, 15, 5, 3, 4, 8, 20, 35, 60],
        "p80_mm":   [130, 155, 150, 75, 28, 10, 6, 8, 15, 35, 60, 100],
    })
    modo_demo = True

if modo_demo:
    modo_datos = "DEMOSTRACIÓN — Ensamble sintético (NO usar para decisiones)"
    df_miembros = generar_ensamble_demo(climatologia, semilla=int(abs(lat_usuario * 1e4)))
else:
    try:
        df_miembros, df_anom, aviso_ensamble = obtener_pronostico_seas5(lat_usuario, lon_usuario)
    except Exception as e:
        st.warning(
            f"No fue posible consultar el ensamble SEAS5 ({e}). "
            "Se activó automáticamente el MODO DEMOSTRACIÓN con datos sintéticos."
        )
        modo_datos = "DEMOSTRACIÓN — Ensamble sintético (NO usar para decisiones)"
        df_miembros = generar_ensamble_demo(climatologia, semilla=int(abs(lat_usuario * 1e4)))

if "DEMOSTRACIÓN" in modo_datos:
    st.error("🧪 **MODO DEMOSTRACIÓN ACTIVO** — Los datos mostrados son sintéticos y "
             "solo ilustran el funcionamiento de la plataforma.")

# ---- Cálculo probabilístico del mes seleccionado ----
probabilidad, umbral_p80, normal_mes, ensamble_mes = calcular_probabilidad_excedencia(
    df_miembros, climatologia, anio_sel, mes_sel
)
n_miembros = int(ensamble_mes["miembro"].nunique()) if not ensamble_mes.empty else 0

# Anomalía (mm/día) del mes seleccionado, si la API la entregó.
anomalia_sel = None
if not df_anom.empty:
    fila_a = df_anom[(df_anom["anio"] == anio_sel) & (df_anom["mes"] == mes_sel)]
    if not fila_a.empty:
        anomalia_sel = float(fila_a["anomalia_mm_dia"].iloc[0])
elif "DEMOSTRACIÓN" in modo_datos and probabilidad is not None:
    # En demo, se deriva el signo de anomalía comparando mediana del ensamble vs normal.
    anomalia_sel = (float(ensamble_mes["total_mm"].median()) - normal_mes) / 30.0

fuera_de_horizonte = probabilidad is None
if fuera_de_horizonte:
    st.info(
        f"ℹ️ **{etiqueta_mes} está fuera del horizonte actual de SEAS5.** El modelo "
        "pronostica ~7 meses desde su última inicialización (se actualiza cada día 5). "
        "Los meses tardíos del verano 2026-2027 se irán habilitando conforme avance el "
        "calendario. Mientras tanto se muestran la climatología ERA5 y el contexto ENFEN."
    )

nivel_riesgo, titulo_riesgo, mensaje_riesgo = evaluar_consecuencias(
    dep_norm, sector_usuario, probabilidad, anomalia_sel
)

# Serie mes a mes de toda la temporada crítica: se calcula UNA sola vez aquí
# y se reutiliza en el gráfico de la Pestaña 2 y en la tabla del reporte PDF.
filas_temporada = []
for etq, a, m in MESES_EVENTO:
    p_mes, u_mes, nrm_mes, _ = calcular_probabilidad_excedencia(df_miembros, climatologia, a, m)
    filas_temporada.append({"mes": etq, "prob": p_mes, "normal": nrm_mes, "p80": u_mes})
df_temporada = pd.DataFrame(filas_temporada)

# =============================================================================
# 9. PANEL PRINCIPAL — PESTAÑAS
# =============================================================================

tab_geo, tab_prob, tab_riesgo, tab_ciencia = st.tabs([
    "🗺️ Visualización Geoespacial (ZOOM)",
    "📊 Análisis Probabilístico de Amenaza",
    "⚠️ Consecuencias y Riesgos Operativos",
    "🔬 Sustento Científico y Reportes",
])

# ---------------------------------------------------------------- Pestaña 1
with tab_geo:
    c1, c2, c3 = st.columns(3)
    c1.metric("Departamento detectado", dep_nombre)
    grupo = ("Costa Norte / Intermedia" if dep_norm in COSTA_NORTE_INTERMEDIA
             else "Sierra Sur / Altiplano" if dep_norm in SIERRA_SUR_ALTIPLANO
             else "Otras regiones")
    c2.metric("Grupo climático ENOS", grupo)
    c3.metric("Radio de operación", f"{RADIO_BUFFER_KM:.0f} km")

    st.caption(
        f"Mapa de calor: señal de anomalía de lluvia de SEAS5 para **{etiqueta_mes}** "
        "(índice donde 50 = normal climatológica). Tonos cian = más lluvioso de lo "
        "normal; tonos marrones = más seco. La probabilidad de excedencia rigurosa "
        "contra el umbral P80 histórico está en la pestaña de Análisis Probabilístico, "
        "calculada en el punto exacto del activo."
    )

    # ---- Construcción (o recuperación cacheada) de las grillas de calor ----
    df_heat_nac = pd.DataFrame()
    df_heat_reg = pd.DataFrame()
    aviso_heat = None
    try:
        puntos_nac = generar_puntos_grilla_nacional(gdf_peru)
        puntos_reg = (generar_puntos_grilla_regional(fila_dep)
                      if fila_dep is not None else [])
        if "DEMOSTRACIÓN" in modo_datos:
            df_heat_nac = generar_grilla_prob_demo(puntos_nac, mes_sel, semilla=mes_sel * 7 + 1)
            df_heat_reg = (generar_grilla_prob_demo(puntos_reg, mes_sel, semilla=mes_sel * 7 + 2)
                           if puntos_reg else pd.DataFrame())
        else:
            df_heat_nac = obtener_probabilidad_grilla(tuple(puntos_nac), anio_sel, mes_sel)
            df_heat_reg = (obtener_probabilidad_grilla(tuple(puntos_reg), anio_sel, mes_sel)
                           if puntos_reg else pd.DataFrame())
            if df_heat_nac.empty:
                aviso_heat = (
                    "El mapa de calor no está disponible para este mes (SEAS5 aún no "
                    "cubre este horizonte o la API no respondió). Se muestran los mapas "
                    "base; el análisis puntual de la Pestaña 2 no se ve afectado."
                )
    except Exception as e:
        aviso_heat = f"No fue posible construir el mapa de calor de lluvia ({e})."

    if aviso_heat:
        st.info("ℹ️ " + aviso_heat)

    # ---- NIVEL 1: Referencia Nacional (todo el Perú) ----
    st.markdown("##### 1 · Referencia Nacional — Perú")
    st.plotly_chart(
        construir_mapa_nacional(gdf_peru, df_heat_nac, fila_dep, lat_usuario, lon_usuario),
        width='stretch',
    )

    # ---- NIVEL 2: Zoom Regional (departamento del activo) ----
    if fila_dep is not None:
        st.markdown(f"##### 2 · Zoom Regional — {dep_nombre}")
        st.plotly_chart(
            construir_mapa_regional(gdf_peru, df_heat_reg, fila_dep, lat_usuario, lon_usuario),
            width='stretch',
        )

        # ---- NIVEL 3: Zoom Local (zona de operación de 10 km) ----
        st.markdown(f"##### 3 · Zoom Local — Zona de operación ({RADIO_BUFFER_KM:.0f} km)")
        indice_local = _indice_en_punto(df_heat_reg, lat_usuario, lon_usuario)
        if indice_local is None:
            indice_local = _indice_en_punto(df_heat_nac, lat_usuario, lon_usuario)
        st.plotly_chart(
            construir_mapa_local(buffer_geo, lat_usuario, lon_usuario, indice_local),
            width='stretch',
        )
        if indice_local is not None:
            estado = ("más húmedo de lo normal" if indice_local > 55 else
                      "más seco de lo normal" if indice_local < 45 else "cercano a lo normal")
            st.caption(f"El relleno del círculo refleja el índice de anomalía en el punto "
                       f"de la planta para {etiqueta_mes}: **{indice_local:.0f}/100** ({estado}).")

    st.caption(
        "Zoom Nacional → Regional → Local. El mapa de calor es una superficie continua "
        "interpolada (los tonos entre los puntos de datos SEAS5 son estimados, no medidos). "
        "El departamento del activo se resalta en ámbar (intersección punto-en-polígono de "
        "Shapely) y el círculo cian delimita el buffer de 10 km proyectado en UTM."
    )

# ---------------------------------------------------------------- Pestaña 2
with tab_prob:
    if fuera_de_horizonte:
        st.subheader("Climatología de referencia (a la espera del horizonte SEAS5)")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Probabilidad de lluvia extrema", f"{probabilidad:.1f}%",
                  help=f"% de miembros del ensamble por encima del percentil {PERCENTIL_EXTREMO} histórico")
        m2.metric(f"Umbral P{PERCENTIL_EXTREMO} (ERA5)", f"{umbral_p80:.1f} mm")
        m3.metric("Normal climatológica", f"{normal_mes:.1f} mm")
        m4.metric("Miembros del ensamble", f"{n_miembros}")

        if aviso_ensamble:
            st.info("ℹ️ " + aviso_ensamble)

    # Curva de probabilidad a lo largo de toda la temporada crítica.
    # (df_temporada ya fue calculado una sola vez en la orquestación principal.)
    fig_temp = go.Figure()
    fig_temp.add_trace(go.Bar(
        x=df_temporada["mes"], y=df_temporada["normal"],
        name="Normal climatológica (mm)", marker_color="#2E5266", opacity=0.8,
    ))
    fig_temp.add_trace(go.Scatter(
        x=df_temporada["mes"], y=df_temporada["p80"],
        name=f"Umbral P{PERCENTIL_EXTREMO} (mm)", mode="lines+markers",
        line=dict(color=COLOR_ADVERTENCIA, dash="dash"),
    ))
    con_prob = df_temporada.dropna(subset=["prob"])
    fig_temp.add_trace(go.Scatter(
        x=con_prob["mes"], y=con_prob["prob"],
        name="Prob. de excedencia (%)", mode="lines+markers+text",
        text=[f"{v:.0f}%" for v in con_prob["prob"]], textposition="top center",
        textfont=dict(color=COLOR_ACENTO),
        line=dict(color=COLOR_ACENTO, width=3), yaxis="y2",
    ))
    fig_temp.add_hline(y=UMBRAL_PROBABILIDAD_CRITICA, line_dash="dot",
                       line_color=COLOR_ALERTA, yref="y2",
                       annotation_text=f"Umbral crítico {UMBRAL_PROBABILIDAD_CRITICA:.0f}%",
                       annotation_font_color=COLOR_ALERTA)
    fig_temp.update_layout(
        template="plotly_dark", paper_bgcolor=COLOR_FONDO, plot_bgcolor=COLOR_PANEL,
        height=470,
        title=dict(
            text="Temporada crítica Oct 2026 – Abr 2027: clima de referencia vs. señal probabilística",
            x=0.02, xanchor="left", y=0.97, yanchor="top",
            font=dict(color="#FFFFFF", size=15),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0,
                    font=dict(color=COLOR_TEXTO)),
        yaxis=dict(title="Precipitación mensual (mm)"),
        yaxis2=dict(title="Probabilidad (%)", overlaying="y", side="right",
                    range=[0, 100], showgrid=False),
        margin=dict(t=95, b=10, l=10, r=10),
    )
    st.plotly_chart(fig_temp, width='stretch')

    # --- Lectura didáctica del gráfico, mes a mes ---
    st.markdown("#### 📖 Cómo leer este gráfico, mes a mes")
    st.markdown(
        f"En una frase: la **línea cian** indica, para cada mes, qué porcentaje de los "
        f"**51 escenarios** del modelo SEAS5 prevé lluvias por encima de lo normal "
        f"(el umbral P{PERCENTIL_EXTREMO} del clima 1991–2020 en el punto exacto de la central). "
        f"Cuanto más alta esté esa línea —y más cerca o por encima de la **línea roja del "
        f"{UMBRAL_PROBABILIDAD_CRITICA:.0f}%**—, mayor es la amenaza de lluvia extrema. "
        f"Las **barras** son la lluvia típica del mes y la **línea ámbar** marca a partir de "
        f"cuánta lluvia se considera \"extrema\"."
    )
    for _linea in narrar_temporada(df_temporada):
        st.markdown(_linea)
    st.caption(
        f"Semáforo de amenaza: 🔴 crítico (≥ {UMBRAL_PROBABILIDAD_CRITICA:.0f}%) · "
        f"🟠 vigilancia ({UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}–{UMBRAL_PROBABILIDAD_CRITICA:.0f}%) · "
        f"🟢 bajo (< {UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}%). "
        "La probabilidad es la fracción de miembros del ensamble cuyo total mensual supera el "
        "umbral extremo; se interpreta como anomalía de área (~36 km) y no reemplaza los "
        "comunicados oficiales de ENFEN/SENAMHI."
    )

# ---------------------------------------------------------------- Pestaña 3
with tab_riesgo:
    clase_css = {"critico": "riesgo-critico", "alto": "riesgo-alto",
                 "normal": "riesgo-normal"}[nivel_riesgo]
    icono = {"critico": "🔴", "alto": "🟠", "normal": "🟢"}[nivel_riesgo]
    st.markdown(
        f"<div class='tarjeta-riesgo {clase_css}'>"
        f"<b>{icono} {titulo_riesgo}</b><br><br>{mensaje_riesgo}</div>",
        unsafe_allow_html=True,
    )
    st.markdown("#### Parámetros que activaron esta evaluación")
    st.dataframe(pd.DataFrame({
        "Parámetro": ["Departamento", "Grupo climático", "Sector", "Mes",
                      "Probabilidad de excedencia P80",
                      "Anomalía SEAS5 (mm/día)", "Umbral crítico configurado"],
        "Valor": [dep_nombre, grupo, sector_usuario, etiqueta_mes,
                  "—" if probabilidad is None else f"{probabilidad:.1f}%",
                  "—" if anomalia_sel is None else f"{anomalia_sel:+.2f}",
                  f"> {UMBRAL_PROBABILIDAD_CRITICA:.0f}%"],
    }), hide_index=True, width='stretch')
    st.caption(
        "La matriz región × sector implementa los mecanismos físicos documentados del ENOS: "
        "convección costera intensificada (huaicos, turbidez, colmatación) en la vertiente "
        "occidental norte, y supresión convectiva (sequía, estrés hídrico) en la sierra sur "
        "y el Altiplano."
    )

# ---------------------------------------------------------------- Pestaña 4
with tab_ciencia:
    st.markdown(f"<div class='panel-enfen'>{TEXTO_ENFEN}</div>", unsafe_allow_html=True)

    st.subheader(f"Dispersión del ensamble SEAS5 — {etiqueta_mes}")
    if not fuera_de_horizonte and n_miembros >= 2:
        fig_violin = go.Figure()
        fig_violin.add_trace(go.Violin(
            y=ensamble_mes["total_mm"], box_visible=True, points="all",
            pointpos=0, jitter=0.35, meanline_visible=True,
            fillcolor="rgba(63,167,214,0.25)", line_color=COLOR_ACENTO,
            marker=dict(size=5, color="#9FD3EC"),
            name=f"{n_miembros} miembros",
        ))
        fig_violin.add_hline(y=umbral_p80, line_dash="dash", line_color=COLOR_ADVERTENCIA,
                             annotation_text=f"P{PERCENTIL_EXTREMO} histórico = {umbral_p80:.0f} mm",
                             annotation_font_color=COLOR_ADVERTENCIA)
        fig_violin.add_hline(y=normal_mes, line_dash="dot", line_color=COLOR_OK,
                             annotation_text=f"Normal = {normal_mes:.0f} mm",
                             annotation_font_color=COLOR_OK)
        fig_violin.update_layout(
            template="plotly_dark", paper_bgcolor=COLOR_FONDO, plot_bgcolor=COLOR_PANEL,
            height=460, yaxis_title="Precipitación mensual total (mm)",
            showlegend=False, margin=dict(t=30),
        )
        st.plotly_chart(fig_violin, width='stretch')
        st.markdown(f"""
**Cómo leer este gráfico (violín de distribución):**

- **Cada punto azul es un miembro del ensamble** — una de las {n_miembros} simulaciones
que el ECMWF corre partiendo de condiciones atmosféricas iniciales ligeramente distintas.
Juntos representan los futuros físicamente plausibles para {etiqueta_mes}.
- **El ancho del violín** en cada altura indica cuántos miembros predicen ese nivel de
lluvia: donde es más ancho, más probable; donde es angosto, menos probable. *La forma
ES la distribución de probabilidad.*
- **La caja central** marca el rango intercuartílico (del 25 % al 75 % de los miembros) y
la línea de la media; resume dónde se concentra el pronóstico.
- **Línea ámbar punteada (P{PERCENTIL_EXTREMO} = {umbral_p80:.0f} mm):** el umbral de lluvia
"extrema" según 30 años de ERA5. **La probabilidad de amenaza es simplemente qué fracción
de los puntos cae por encima de esta línea.**
- **Línea verde punteada (Normal = {normal_mes:.0f} mm):** la lluvia típica del mes.

En términos operativos: mientras más masa del violín quede **por encima** de la línea ámbar,
mayor es la probabilidad de que {etiqueta_mes} traiga lluvias capaces de gatillar los modos
de falla de tu activo. Un violín angosto = pronóstico confiable; uno muy ancho = alta
incertidumbre, que es en sí misma información para la gestión del riesgo.
""")
    else:
        st.info("El gráfico de dispersión del ensamble se habilitará cuando el mes "
                "seleccionado entre en el horizonte de pronóstico de SEAS5.")

    with st.expander("📖 Ficha Metodológica de Transparencia (Glass-Box)"):
        st.markdown(f"""
**1. Marco conceptual.** Riesgo = *Amenaza × Exposición × Vulnerabilidad* (IPCC AR6).
Esta plataforma cuantifica la **amenaza** de forma probabilística y la cruza con la
**exposición** geoespacial exacta del activo (punto + buffer de {RADIO_BUFFER_KM:.0f} km).

**2. Normal climatológica.** Reanálisis **ERA5** del programa Copernicus (Unión Europea),
periodo de referencia **1991-2020** (estándar OMM), agregado a totales mensuales en el
píxel del activo. El umbral de "lluvia extrema" es el **percentil {PERCENTIL_EXTREMO}**
de la distribución empírica de 30 años de cada mes calendario — equivalente conceptual
del mapeo de cuantiles usado para corrección de sesgo en estudios CMIP6.

**3. Pronóstico estacional.** **ECMWF SEAS5**, sistema operativo de **51 miembros**
(resolución ~36 km, actualización mensual el día 5, horizonte 7 meses), distribuido como
dato abierto a través de la Seasonal Forecast API de Open-Meteo. La probabilidad reportada
es la **frecuencia relativa de excedencia** del umbral dentro del ensamble:
`P = #(miembros > P{PERCENTIL_EXTREMO}) / N × 100`.

**4. Contexto de escenarios.** Los modelos globales **CMIP6** del IPCC y sus trayectorias
SSP enmarcan la no-estacionariedad del clima: la variabilidad ENOS se superpone al
calentamiento antropogénico, por lo que la climatología histórica se usa como referencia
de umbral y no como pronóstico.

**5. Limitaciones declaradas.** SEAS5 no está bias-corregido a escala local (interpretar
como anomalía de área); los meses tardíos del verano entran al horizonte progresivamente;
la matriz de consecuencias es paramétrica (región × sector) y debe calibrarse con las
curvas de daño específicas de cada planta.

**6. Geoespacial.** Límites ADM1 de **geoBoundaries** (licencia abierta), intersección
punto-en-polígono con Shapely/GEOS y buffer métrico en proyección UTM local.
""")

    st.subheader("📄 Reporte ejecutivo descargable")
    if fuera_de_horizonte:
        st.caption("El PDF incluirá la climatología y el contexto ENFEN; la probabilidad "
                   "se reportará como no disponible para este mes.")
    contexto_pdf = {
        "lat": lat_usuario, "lon": lon_usuario, "departamento": dep_nombre,
        "sector": sector_usuario, "mes_etiqueta": etiqueta_mes,
        "modo_datos": modo_datos,
        "probabilidad": probabilidad if probabilidad is not None else 0.0,
        "umbral": umbral_p80, "normal": normal_mes, "n_miembros": n_miembros,
        "riesgo_titulo": titulo_riesgo, "riesgo_mensaje": mensaje_riesgo,
        "temporada": df_temporada.to_dict("records"),
    }
    try:
        pdf_bytes = generar_pdf(contexto_pdf)
        st.download_button(
            label="⬇️ Descargar Reporte PDF",
            data=pdf_bytes,
            file_name=f"reporte_riesgo_climatico_{etiqueta_mes.replace(' ', '_').lower()}.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as e:
        st.error(f"No fue posible generar el PDF en este momento: {e}")


# =============================================================================
# 10. PIE DE PAGINA GLOBAL
# =============================================================================
st.divider()
st.caption(
    f"© 2026 {EMPRESA}  ·  Autor: {AUTOR_CONTACTO}  ·  **{VERSION_ESTADO}.** "
    "Los resultados son orientativos y no reemplazan el criterio técnico ni los "
    "comunicados oficiales de ENFEN/SENAMHI."
)
