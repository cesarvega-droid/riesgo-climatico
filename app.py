# =============================================================================
#  RIESGO CLIMÁTICO PROBABILÍSTICO — EL NIÑO 2026-2027 (PERÚ)
#  Herramienta de evaluación de amenaza de lluvias extremas para
#  infraestructura crítica (Hidroeléctricas, Saneamiento, Industria).
#
#  Arquitectura: 100% open-source, sin base de datos.
#    - Frontend      : Streamlit (tema corporativo azul marino)
#    - Geoespacial   : GeoPandas + Shapely + Plotly Mapbox (procesado en RAM)
#    - Mapa base     : CARTO dark (requiere API key gratuita -> st.secrets)
#    - Amenaza       : Open-Meteo Seasonal API -> ECMWF SEAS5 (51 miembros)
#    - Climatología  : Open-Meteo Archive API  -> Reanálisis ERA5 (1991-2020)
#    - Reporte       : fpdf2 (PDF autocontenido, sin dependencias gráficas)
#
#  Cambios oct-2026: semáforo con P90 (P80 queda como señal), mediana y P90 del
#  ensamble en mm, referencia Niño 1997-98 / 2017, diagnóstico de sesgo SEAS5 vs
#  ERA5, corrección Lima Metropolitana/Callao, ENFEN N°17-2026 y guiones en PDF.
#
#  Ejecución local:
#    pip install streamlit geopandas shapely plotly requests pandas numpy fpdf2
#    streamlit run app.py
# =============================================================================

import io
import json
import os
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

# Paleta corporativa UNLEASHING POWER.
# Criterio de diseño: la identidad viste el CROMO (fondos, paneles, acentos,
# tipografía); las señales FUNCIONALES (semáforo de riesgo y escala del mapa de
# calor) conservan su código de color porque comunican estado, no marca. Pintar
# de púrpura un semáforo lo vuelve bonito e ilegible.
UP_PURPURA = "#50164A"         # Púrpura corporativo (reservado para impresos)
UP_LOGO = "#701E63"            # Púrpura del logotipo (tono medio de la rampa)
UP_MAGENTA = "#84247B"         # Magenta corporativo (acento vivo, bordes)
UP_ORO = "#C9A227"             # Oro corporativo (realces y reglas finas)

COLOR_FONDO = "#1A0718"        # Ciruela casi negro (fondo principal)
COLOR_ACENTO = "#DFA0D6"       # Orquídea claro: magenta legible sobre ciruela
COLOR_TEXTO = "#EFE2EC"        # Blanco rosado (texto general)
COLOR_TEXTO_TENUE = "#C4A8BF"  # Texto secundario y pies de figura

# --- Señales funcionales: NO son colores de marca, son código de estado ---
COLOR_ALERTA = "#E4572E"       # Naranja rojizo (peligro crítico)
COLOR_ADVERTENCIA = "#F5B841"  # Ámbar (vigilancia) — vecino natural del oro UP
COLOR_OK = "#59C9A5"           # Verde azulado (condición normal)

# Logotipo: variante monocroma blanca sobre fondo transparente, pensada para
# fondos oscuros. Si el archivo no está en el repositorio, la app no falla:
# muestra el nombre tipográfico como respaldo.
RUTA_LOGO = "logo_up_blanco.png"


def mostrar_logo(contenedor, ancho=210):
    """Pinta el logotipo, con respaldo tipográfico si falta el archivo."""
    try:
        if os.path.exists(RUTA_LOGO):
            contenedor.image(RUTA_LOGO, width=ancho)
            return
    except Exception:
        pass
    contenedor.markdown(
        "<div class='marca-respaldo'>UNLEASHING<br>POWER</div>",
        unsafe_allow_html=True,
    )


# --- Tonos para el ÁREA DE TRAZADO de los gráficos --------------------------
# Criterio: el dato manda. El fondo del gráfico baja casi al nivel del fondo de
# página (solo lo suficiente para delimitarlo), la rejilla queda apenas
# insinuada, y el color corporativo se reserva para el MARCO del recuadro. Así
# la transición de color es tranquila y lo que resalta es la información.
COLOR_LIENZO = "#210B1F"                  # Ciruela muy bajo (fondo de trazado)
COLOR_REJILLA = "rgba(223,160,214,0.13)"  # Rejilla apenas perceptible
COLOR_MARCO = UP_MAGENTA                  # Delineado corporativo del recuadro
COLOR_BARRA_NORMAL = "#8A3A80"            # Ciruela medio para barras de referencia


def estilo_grafico(fig):
    """
    Aplica el tratamiento común a todos los gráficos: lienzo bajo, rejilla
    tenue y marco en color corporativo. Se llama DESPUÉS de update_layout
    para que prevalezca sobre los ajustes particulares de cada figura.
    """
    fig.update_layout(
        paper_bgcolor=COLOR_FONDO,
        plot_bgcolor=COLOR_LIENZO,
        font=dict(color=COLOR_TEXTO),
    )
    marco = dict(showline=True, linecolor=COLOR_MARCO, linewidth=1, mirror=True,
                 gridcolor=COLOR_REJILLA, zeroline=False)
    fig.update_xaxes(**marco)
    fig.update_yaxes(**marco)
    return fig


st.markdown(
    f"""
    <style>
      .stApp {{ background-color: {COLOR_FONDO}; color: {COLOR_TEXTO}; }}
      section[data-testid="stSidebar"] {{
          background-color: {COLOR_FONDO};
          border-right: 1px solid {UP_MAGENTA};
      }}
      h1, h2, h3, h4 {{ color: #FFFFFF !important; }}
      /* Regla fina en oro bajo el título principal: firma visual de la marca. */
      h1 {{ border-bottom: 2px solid {UP_ORO}; padding-bottom: 10px; }}
      div[data-testid="stMetricValue"] {{ color: {COLOR_ACENTO}; }}
      .marca-respaldo {{
          color: #FFFFFF; font-weight: 800; letter-spacing: 0.14em;
          font-size: 1.05rem; line-height: 1.25; border-left: 5px solid {UP_ORO};
          padding-left: 12px; margin-bottom: 14px;
      }}
      .panel-enfen {{
          background-color: #2A0E27; border: 1px solid {UP_MAGENTA};
          border-left: 6px solid {UP_ORO};
          padding: 14px 18px; border-radius: 6px; font-size: 0.92rem;
          line-height: 1.5; margin-bottom: 12px;
      }}
      .tarjeta-riesgo {{
          padding: 16px 20px; border-radius: 8px; margin-bottom: 10px;
          font-size: 0.95rem; line-height: 1.55;
      }}
      .riesgo-critico  {{ background-color: rgba(228, 87, 46, 0.18); border-left: 6px solid {COLOR_ALERTA}; }}
      .riesgo-alto     {{ background-color: rgba(245, 184, 65, 0.15); border-left: 6px solid {COLOR_ADVERTENCIA}; }}
      .riesgo-normal   {{ background-color: rgba(89, 201, 165, 0.12); border-left: 6px solid {COLOR_OK}; }}

      /* ---------- CORRECCIÓN DE CONTRASTE (legibilidad sobre fondo oscuro) ----------
         Si la app corre sin el tema oscuro de .streamlit/config.toml, Streamlit usa
         su tema claro por defecto y las etiquetas quedan gris-oscuro sobre ciruela
         (ilegibles). Estas reglas fuerzan texto claro en los elementos de
         interfaz, sin tocar el interior de los inputs (que tienen fondo blanco). */
      section[data-testid="stSidebar"] label p,
      section[data-testid="stSidebar"] div[data-testid="stWidgetLabel"] p,
      section[data-testid="stSidebar"] .stMarkdown p {{
          color: {COLOR_TEXTO} !important;
      }}
      div[data-testid="stCaptionContainer"] p,
      div[data-testid="stCaptionContainer"] {{
          color: {COLOR_TEXTO_TENUE} !important;   /* captions y subtítulos */
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
          color: {COLOR_TEXTO_TENUE} !important;
          opacity: 1 !important;
      }}
      div[data-testid="stMetricValue"],
      div[data-testid="stMetricValue"] * {{
          color: {COLOR_ACENTO} !important;    /* valor de st.metric */
      }}
      button[data-baseweb="tab"] p {{
          color: {COLOR_TEXTO} !important;     /* títulos de pestañas no activas */
      }}
      /* Pestaña activa subrayada en oro corporativo. */
      button[data-baseweb="tab"][aria-selected="true"] p {{ color: #FFFFFF !important; }}
      div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {{
          background-color: {UP_ORO} !important;
      }}
      .panel-enfen {{ color: #FBF3F9; }}
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

# Área local de aporte por defecto (m²) para traducir lámina de lluvia (mm) a
# volumen (m³). Son órdenes de magnitud iniciales por tipología de activo: el
# usuario debe ajustarlos a la huella real de su instalación.
# NOTA DE ALCANCE: el pronóstico SEAS5 es PUNTUAL (píxel del activo). Usar un
# área de escala cuenca asumiría lluvia uniforme sobre toda ella, hipótesis que
# este dato no sostiene. Por eso el campo es "área LOCAL de aporte": techos,
# patios, plataformas, canal, accesos y franja de servidumbre.
AREA_APORTE_DEFECTO = {
    "Generación Hidroeléctrica": 30_000,
    "Generación Termoeléctrica": 50_000,
    "Generación Solar": 200_000,
    "Generación Eólica": 100_000,
    "Subestación": 10_000,
    "Tramo de Línea de Transmisión": 5_000,
    "Saneamiento/Tratamiento de Agua": 20_000,
    "Infraestructura Industrial General": 20_000,
}

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
    # geoBoundaries separa Lima Metropolitana y el Callao del departamento de
    # Lima; sin estos nombres, Lurín, Chosica o el Callao caían en "Otras
    # regiones" y la sección de consecuencias quedaba vacía.
    "municipalidad metropolitana de lima", "provincia constitucional del callao",
}
SIERRA_SUR_ALTIPLANO = {
    "puno", "cusco", "cuzco", "arequipa", "apurimac", "huancavelica", "ayacucho",
}

# Fuentes de datos abiertas (sin API key)
URL_GEOJSON_PERU = (
    "https://github.com/wmgeolab/geoBoundaries/raw/90a1d52/"
    "releaseData/gbOpen/PER/ADM1/geoBoundaries-PER-ADM1.geojson"
)
URL_API_ESTACIONAL = "https://seasonal-api.open-meteo.com/v1/seasonal"
URL_API_HISTORICA = "https://archive-api.open-meteo.com/v1/archive"


# --- Mapa base CARTO -----------------------------------------------------
# Desde 2026 CARTO exige API key en sus teselas raster: sin clave, las teselas
# llegan con una marca de agua "API KEY REQUIRED" estampada en la imagen.
# La clave es gratuita (carto.com/basemaps/apikey, hasta 5 M teselas/mes) y se
# guarda FUERA del código: en .streamlit/secrets.toml (local) y en el panel
# Secrets de Streamlit Cloud (producción), siempre como  CARTO_KEY = "...".
# Si no hay clave la app NO falla: cae a OpenStreetMap, que no exige clave.
def _leer_clave_carto() -> str:
    """Lee CARTO_KEY de st.secrets tolerando la ausencia del archivo."""
    try:
        return str(st.secrets.get("CARTO_KEY", "")).strip()
    except Exception:
        return ""


CARTO_KEY = _leer_clave_carto()
CARTO_TESELAS_DARK = (
    "https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key="
    + CARTO_KEY
)
# Estilo VECTORIAL de CARTO. Es el que CARTO recomienda porque el servicio
# raster está en retiro, y solo funciona sobre el motor MapLibre (Plotly >= 6).
CARTO_ESTILO_VECTORIAL = (
    "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
    + (f"?key={CARTO_KEY}" if CARTO_KEY else "")
)

# --- Compatibilidad Plotly: trazas mapbox (<6) vs. map/MapLibre (>=6) -----
# Plotly 6 ELIMINÓ go.Scattermapbox / go.Choroplethmapbox y la clave de layout
# "mapbox", reemplazándolos por go.Scattermap / go.Choroplethmap y la clave
# "map". La app detecta en tiempo de ejecución qué API está disponible, de modo
# que funciona igual con Plotly 5 y con Plotly 6/7 sin tocar el código.
PLOTLY_MAPLIBRE = hasattr(go, "Choroplethmap")
if PLOTLY_MAPLIBRE:
    TrazaPuntos, TrazaCoropleta, CLAVE_LAYOUT_MAPA = go.Scattermap, go.Choroplethmap, "map"
else:
    TrazaPuntos, TrazaCoropleta, CLAVE_LAYOUT_MAPA = (
        go.Scattermapbox, go.Choroplethmapbox, "mapbox"
    )
# La atribución a CARTO y OpenStreetMap es obligatoria por los términos del
# tier gratuito; Plotly la renderiza en la esquina del mapa.
ATRIBUCION_BASE = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    '&copy; <a href="https://carto.com/attributions">CARTO</a>'
)

UMBRAL_PROBABILIDAD_CRITICA = 55.0  # % de miembros sobre el percentil del SEMÁFORO
# Dos umbrales climatológicos (ERA5 1991-2020, total mensual):
#  - P80 = SEÑAL HÚMEDA: "mes más lluvioso de lo habitual" (2 de cada 10 años).
#          Se reporta como contexto; ya NO define el semáforo.
#  - P90 = SEMÁFORO: "mes de lluvia fuerte" (1 de cada 10 años). Coherente con
#          el criterio SENAMHI/ENFEN de "lluvias fuertes" = P90 (que ellos aplican
#          a escala diaria; aquí se aplica al total mensual).
PERCENTIL_EXTREMO = 80              # Señal húmeda (contexto)
PERCENTIL_SEMAFORO = 90             # Umbral que gobierna el semáforo
RADIO_BUFFER_KM = 10.0              # Zona de operación local alrededor de la planta

# Lámina de referencia baja: si el umbral P90 del mes es menor a este valor, la
# señal describe un mes anómalo para un clima muy seco, no necesariamente lluvias
# intensas. Se agrega una nota explicativa en la narrativa (parámetro calibrable).
LAMINA_REFERENCIA_BAJA_MM = 10.0

# Años Niño de referencia (total mensual ERA5 en el punto del activo):
#  - El Niño 1997-98: octubre 1997 a abril 1998.
#  - El Niño Costero 2017: enero a abril 2017.
# Para cada mes se toma el mayor de los disponibles como "referencia Niño".
MESES_NINO_9798 = {10: 1997, 11: 1997, 12: 1997, 1: 1998, 2: 1998, 3: 1998, 4: 1998}
MESES_NINO_2017 = {1: 2017, 2: 2017, 3: 2017, 4: 2017}

# Diagnóstico de sesgo: razón entre la normal del propio SEAS5 (hindcasts) y la
# normal ERA5. Fuera de este rango se considera que el modelo tiene sesgo.
RAZON_SESGO_HUMEDO = 1.5
RAZON_SESGO_SECO = 0.67

# Umbral intermedio (didáctico) para clasificar la amenaza mensual en la Pestaña 2.
UMBRAL_PROBABILIDAD_VIGILANCIA = 40.0  # % — entre este valor y el crítico = vigilancia

# --- Identidad / autoría de la plataforma ---
EMPRESA = "Unleashing Power | Lima - Perú"
AUTOR_CONTACTO = "cesar.vega@unleashing-power.com"
VERSION_ESTADO = "Versión BETA — herramienta en desarrollo"

# Contexto oficial hardcodeado según especificación del proyecto.
# NOTA DE MANTENIMIENTO: actualizar este bloque con cada nuevo comunicado ENFEN.
#   Vigente: Comunicado N°17-2026 (28/09/2026). Próximo: 15/10/2026.
TEXTO_ENFEN = (
    "<b>Contexto Oficial ENFEN (Comunicado N°17-2026, 28/09/2026):</b> "
    "Alerta de El Niño Costero vigente. El Niño Costero (región Niño 1+2) se "
    "mantendría con magnitud <b>extraordinaria</b> hasta enero de 2027, "
    "debilitándose hacia el otoño; El Niño en la región Niño 3.4 se mantendría "
    "<b>muy fuerte</b> hasta enero de 2027. Para octubre-diciembre se prevén "
    "lluvias superiores a lo normal en la costa norte y central, y para el "
    "verano 2027, en la costa norte, costa central y sierra norte occidental."
)
TEXTO_ENFEN_PDF = (
    "Contexto Oficial ENFEN (Comunicado N°17-2026, 28/09/2026): Alerta de El Niño "
    "Costero vigente. El Niño Costero (región Niño 1+2) se mantendría con magnitud "
    "extraordinaria hasta enero de 2027, debilitándose hacia el otoño; El Niño en la "
    "región Niño 3.4 se mantendría muy fuerte hasta enero de 2027. Para "
    "octubre-diciembre se prevén lluvias superiores a lo normal en la costa norte y "
    "central, y para el verano 2027, en la costa norte, costa central y sierra norte "
    "occidental. Próximo comunicado oficial: 15/10/2026."
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
    de excedencia rigurosa contra los umbrales P80/P90 históricos vive en la Pestaña 2,
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

    fig.add_trace(TrazaCoropleta(
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
    fig.add_trace(TrazaCoropleta(
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
    fig.add_trace(TrazaCoropleta(
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
    fig.add_trace(TrazaPuntos(
        lat=[lat], lon=[lon],
        mode="markers+text" if con_texto else "markers",
        marker=dict(size=14, color=COLOR_ALERTA),
        text=["  Central"] if con_texto else None,
        textposition="middle right",
        textfont=dict(color="#FFFFFF", size=12),
        hovertemplate=f"Lat: {lat:.5f}<br>Lon: {lon:.5f}<extra>Central</extra>",
    ))


def _base_mapa() -> dict:
    """
    Define el mapa base según el motor disponible y la presencia de clave:

      · Plotly >= 6 (MapLibre) + clave -> estilo VECTORIAL de CARTO. Es la ruta
        recomendada por CARTO: cartografía más nítida y sin marca de agua.
      · Plotly 5 (Mapbox GL) + clave   -> teselas RASTER de CARTO autenticadas.
      · Sin clave                      -> OpenStreetMap, que no exige clave.
        La app sigue operativa; solo pierde el fondo oscuro corporativo.
    """
    if not CARTO_KEY:
        return dict(style="open-street-map")
    if PLOTLY_MAPLIBRE:
        return dict(style=CARTO_ESTILO_VECTORIAL)
    return dict(
        style="white-bg",
        layers=[{
            "below": "traces",
            "sourcetype": "raster",
            "sourceattribution": ATRIBUCION_BASE,
            "source": [CARTO_TESELAS_DARK],
        }],
    )


def _layout_mapa(fig, centro, zoom, altura):
    # La clave del layout cambia de nombre entre APIs ("mapbox" vs. "map"),
    # por eso se arma dinámicamente en lugar de pasarla como palabra fija.
    fig.update_layout(
        **{CLAVE_LAYOUT_MAPA: dict(center=centro, zoom=zoom, **_base_mapa())},
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
        fig.add_trace(TrazaPuntos(
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
        .agg(normal_mm="mean",
             p80_mm=lambda s: float(np.percentile(s, PERCENTIL_EXTREMO)),
             p90_mm=lambda s: float(np.percentile(s, PERCENTIL_SEMAFORO)))
        .reset_index()
    )

    # Referencias Niño: total mensual observado (ERA5) en el mismo mes de los
    # eventos 1997-98 y 2017, en el punto del activo.
    def _total(anio, mes):
        fila = mensual[(mensual["anio"] == anio) & (mensual["mes"] == mes)]
        return float(fila["pp"].iloc[0]) if not fila.empty else np.nan

    resumen["nino9798_mm"] = [
        _total(MESES_NINO_9798[m], m) if m in MESES_NINO_9798 else np.nan
        for m in resumen["mes"]
    ]
    resumen["nino2017_mm"] = [
        _total(MESES_NINO_2017[m], m) if m in MESES_NINO_2017 else np.nan
        for m in resumen["mes"]
    ]
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
            "forecast_days": 215,   # Igual que en la grilla: sin esto el dato
                                    # mensual se corta antes de enero/febrero.
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

    sel = _miembros_del_mes(df_miembros, anio, mes)
    if sel.empty:
        return None, umbral, normal, sel

    valores = sel["total_mm"].to_numpy()
    probabilidad = 100.0 * float(np.mean(valores > umbral))
    return probabilidad, umbral, normal, sel


def _miembros_del_mes(df_miembros, anio, mes):
    """Filas del ensamble (un total mensual por miembro) para un mes dado."""
    if df_miembros is None or df_miembros.empty:
        return pd.DataFrame(columns=["anio", "mes", "miembro", "total_mm"])
    return df_miembros[(df_miembros["anio"] == anio) & (df_miembros["mes"] == mes)]


def _valor(fila, columna):
    """Lee una columna de la climatología como float (NaN si no existe)."""
    if columna not in fila.index:
        return np.nan
    v = pd.to_numeric(fila[columna], errors="coerce")
    return float(v) if pd.notna(v) else np.nan


def referencia_nino(fila_clima):
    """
    Mayor total mensual entre los meses Niño de referencia disponibles
    (1997-98 y 2017) para ese mes calendario. Devuelve (mm, etiqueta_año).
    """
    mes = int(fila_clima["mes"])
    candidatos = []
    v9798 = _valor(fila_clima, "nino9798_mm")
    if np.isfinite(v9798) and mes in MESES_NINO_9798:
        candidatos.append((v9798, str(MESES_NINO_9798[mes])))
    v2017 = _valor(fila_clima, "nino2017_mm")
    if np.isfinite(v2017) and mes in MESES_NINO_2017:
        candidatos.append((v2017, str(MESES_NINO_2017[mes])))
    if not candidatos:
        return np.nan, None
    return max(candidatos, key=lambda c: c[0])


def resumen_mes(df_miembros, climatologia, etiqueta, anio, mes):
    """
    Todas las métricas de un mes de la temporada, en un solo diccionario:
      - Clima ERA5: normal, P80 (señal), P90 (semáforo), referencia Niño.
      - Pronóstico SEAS5: mediana y P90 del ensamble (mm) y las probabilidades
        de superar P80, P90 y la referencia Niño.
    La clave "prob" es la probabilidad que gobierna el SEMÁFORO (> P90).
    """
    fila_c = climatologia.loc[climatologia["mes"] == mes].iloc[0]
    normal = _valor(fila_c, "normal_mm")
    p80 = _valor(fila_c, "p80_mm")
    p90 = _valor(fila_c, "p90_mm")
    ref_mm, ref_anio = referencia_nino(fila_c)

    sel = _miembros_del_mes(df_miembros, anio, mes)
    valores = sel["total_mm"].to_numpy(dtype=float) if not sel.empty else np.array([])
    valores = valores[np.isfinite(valores)]

    def _prob(umbral):
        if valores.size == 0 or not np.isfinite(umbral):
            return None
        return 100.0 * float(np.mean(valores > umbral))

    mediana_ens, p90_ens = estadisticos_ensamble(sel)
    return {
        "mes": etiqueta, "anio": anio, "num_mes": mes,
        "normal": normal, "p80": p80, "p90": p90,
        "ref_nino_mm": ref_mm, "ref_nino_anio": ref_anio,
        "prob": _prob(p90),            # SEMÁFORO (> P90)
        "prob_p80": _prob(p80),        # señal húmeda (> P80)
        "prob_ref": _prob(ref_mm),     # supera el mes Niño de referencia
        "mediana_ens": mediana_ens, "p90_ens": p90_ens,
        "n_miembros": int(valores.size),
    }


def diagnostico_sesgo(df_miembros, df_anom, climatologia):
    """
    Diagnóstico de sesgo del modelo en el punto del activo.

    Open-Meteo entrega, por mes, la media del ensamble y su ANOMALÍA respecto a
    la climatología del propio SEAS5 (calculada con sus pronósticos
    retrospectivos). Por tanto:
        normal_SEAS5 = media - anomalía
    Comparar esa normal con la normal ERA5 indica si el modelo "cree" que el
    lugar es más lluvioso (razón > 1) o más seco (razón < 1) de lo que registra
    el reanálisis. Una razón alta en la costa hiperárida infla la probabilidad
    de superar umbrales ERA5 de pocos milímetros.

    Unidades: se verifican empíricamente comparando la media mensual de la API
    con el total mensual promedio de los 51 miembros diarios (ya descargados):
    ~días del mes -> la API está en mm/día; ~1 -> la API está en mm/mes.

    Devuelve (DataFrame, dict_meta). DataFrame vacío si no hay datos.
    """
    meta = {"unidad": "no disponible", "factor": None, "mensaje": None}
    if df_anom is None or df_anom.empty or df_miembros is None or df_miembros.empty:
        meta["mensaje"] = ("No hay dato mensual de anomalías de SEAS5 en esta corrida (modo "
                           "demostración o falla de la API); el diagnóstico no está disponible.")
        return pd.DataFrame(), meta

    medias_ens = (df_miembros.groupby(["anio", "mes"])["total_mm"].mean()
                  .rename("media_ens_mm").reset_index())
    base = df_anom.merge(medias_ens, on=["anio", "mes"], how="inner")
    base = base[(base["media_mm_dia"] > 0) & np.isfinite(base["media_ens_mm"])]
    if base.empty:
        meta["mensaje"] = "No hay meses comunes entre el dato mensual y el diario."
        return pd.DataFrame(), meta

    factor = float(base["media_ens_mm"].sum() / base["media_mm_dia"].sum())
    meta["factor"] = factor
    if 20.0 <= factor <= 40.0:
        meta["unidad"] = "mm/día"
        conv = {(r.anio, r.mes): pd.Period(f"{r.anio}-{r.mes:02d}").days_in_month
                for r in df_anom.itertuples()}
    elif 0.6 <= factor <= 1.6:
        meta["unidad"] = "mm/mes"
        conv = {(r.anio, r.mes): 1.0 for r in df_anom.itertuples()}
    else:
        meta["unidad"] = "no identificada"
        meta["mensaje"] = (f"La relación entre el dato mensual y el diario ({factor:.2f}) no "
                           "corresponde a mm/día ni a mm/mes; revisar la API antes de usar "
                           "este diagnóstico.")
        return pd.DataFrame(), meta

    filas = []
    for etiqueta, anio, mes in MESES_EVENTO:
        fila_a = df_anom[(df_anom["anio"] == anio) & (df_anom["mes"] == mes)]
        normal_era5 = float(climatologia.loc[climatologia["mes"] == mes, "normal_mm"].iloc[0])
        if fila_a.empty:
            filas.append({"mes": etiqueta, "normal_era5": normal_era5,
                          "normal_seas5": None, "razon": None, "lectura": "sin dato"})
            continue
        media = float(fila_a["media_mm_dia"].iloc[0])
        anom = float(fila_a["anomalia_mm_dia"].iloc[0])
        normal_seas5 = max(media - anom, 0.0) * conv[(anio, mes)]
        razon = normal_seas5 / normal_era5 if normal_era5 > 0.05 else None
        if razon is None:
            lectura = "normal ERA5 ~0"
        elif razon > RAZON_SESGO_HUMEDO:
            lectura = "modelo más húmedo"
        elif razon < RAZON_SESGO_SECO:
            lectura = "modelo más seco"
        else:
            lectura = "consistente"
        filas.append({"mes": etiqueta, "normal_era5": normal_era5,
                      "normal_seas5": normal_seas5, "razon": razon, "lectura": lectura})
    return pd.DataFrame(filas), meta


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


# -----------------------------------------------------------------------------
# 5.b CATÁLOGO RCM DE MODOS DE FALLA POR SECTOR (amenaza: lluvia extrema)
# -----------------------------------------------------------------------------
# Lógica de diseño: el modo de falla es una propiedad del activo, no del mes.
# Lo que cambia con la severidad del mes es (a) QUÉ modos se vuelven creíbles y
# (b) cuál domina. Por eso cada entrada carga dos atributos de catálogo:
#   - "desde"      : nivel mínimo del semáforo en que el modo se considera activo
#   - "criticidad" : severidad relativa 1-5, usada para ordenar y quedarse con
#                    los tres dominantes del nivel vigente
# Con un solo catálogo por sector, la app muestra tres modos distintos según el
# mes seleccionado sin duplicar contenido ni multiplicar el mantenimiento.
#
# ESTADO: borrador técnico pendiente de validación de ingeniería. Los umbrales
# de activación y la criticidad son el núcleo calibrable de la herramienta.

NIVELES_ORDEN = {"bajo": 0, "vigilancia": 1, "critico": 2}
ETIQUETA_NIVEL = {"bajo": "🟢 Bajo", "vigilancia": "🟠 Vigilancia", "critico": "🔴 Crítico"}

MODOS_FALLA_LLUVIA = {
    "Generación Hidroeléctrica": [
        {"modo": "Colmatación acelerada de bocatoma y desarenador",
         "mecanismo": "Arrastre de sólidos por precipitación intensa en cuenca alta",
         "efecto": "Purgas forzadas y pérdida de generación entregable",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Obstrucción de rejas por material flotante",
         "mecanismo": "Transporte de troncos y residuos durante crecidas",
         "efecto": "Pérdida de carga en la captación y derate de la unidad",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Erosión de inyectores/agujas y rodete por sólidos en suspensión",
         "mecanismo": "Abrasión hidráulica sostenida del caudal turbinado",
         "efecto": "Caída de eficiencia y adelanto del overhaul mayor",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Turbidez por encima del límite de operación de turbinas",
         "mecanismo": "Pico de concentración de sólidos en suspensión",
         "efecto": "Parada preventiva prolongada de la central",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Anegamiento de fosa de drenaje y sótano de casa de máquinas",
         "mecanismo": "Escorrentía pluvial que supera la capacidad de bombeo instalada",
         "efecto": "Riesgo eléctrico e indisponibilidad de servicios auxiliares",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Flujo de detritos (huaico) sobre canal de conducción y vía de acceso",
         "mecanismo": "Activación de quebradas secas por precipitación torrencial",
         "efecto": "Indisponibilidad prolongada y pérdida de accesibilidad",
         "desde": "critico", "criticidad": 5},
    ],
    "Generación Termoeléctrica": [
        {"modo": "Obstrucción de filtros y rejillas del sistema de refrigeración",
         "mecanismo": "Sólidos en suspensión en el agua de captación",
         "efecto": "Derate por alta temperatura de condensador",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Saturación del drenaje pluvial del patio de tanques",
         "mecanismo": "Escorrentía sobre áreas impermeables y bunds de contención",
         "efecto": "Acumulación de agua y riesgo de arrastre de contaminantes",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Colmatación del filtro de aire de admisión",
         "mecanismo": "Humedad y material particulado en suspensión",
         "efecto": "Pérdida de potencia y heat rate degradado en turbina de gas",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Inundación de fosas de bombas de captación y sótanos",
         "mecanismo": "Escorrentía y ascenso freático que superan el drenaje de diseño",
         "efecto": "Pérdida de agua de refrigeración y parada de unidad",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Interrupción del suministro de combustible por pérdida de vías",
         "mecanismo": "Corte de accesos por inundación pluvial o huaico",
         "efecto": "Reducción de autonomía y parada por agotamiento de inventario",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Inundación de sala eléctrica y centro de control de motores",
         "mecanismo": "Lámina de agua que alcanza el nivel de tableros",
         "efecto": "Indisponibilidad total de la unidad y daño mayor de equipos",
         "desde": "critico", "criticidad": 5},
    ],
    "Generación Solar": [
        {"modo": "Reducción de irradiancia por nubosidad convectiva persistente",
         "mecanismo": "Cobertura nubosa sostenida asociada a la fase cálida del ENOS",
         "efecto": "Déficit de energía generada frente al presupuesto del periodo",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Anegamiento de zanjas de canalización y cajas de conexión",
         "mecanismo": "Escorrentía superficial sobre el terreno del parque",
         "efecto": "Fallas de aislamiento en DC y pérdida de strings",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Socavación de hincados y pérdida de alineación de mesas",
         "mecanismo": "Erosión del suelo alrededor de las fundaciones",
         "efecto": "Desalineación de seguidores y sobreesfuerzo estructural",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Ingreso de agua a inversores y centros de transformación",
         "mecanismo": "Lámina de agua sobre plataformas a nivel de suelo",
         "efecto": "Disparo e indisponibilidad de bloques completos de generación",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Pérdida de caminos internos y acceso para O&M",
         "mecanismo": "Erosión y lodo en la red vial del parque",
         "efecto": "Incremento del MTTR ante cualquier falla",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Flujo de lodo sobre el campo fotovoltaico",
         "mecanismo": "Huaico o escorrentía concentrada desde quebrada adyacente",
         "efecto": "Daño físico de módulos y estructura, pérdida prolongada",
         "desde": "critico", "criticidad": 5},
    ],
    "Generación Eólica": [
        {"modo": "Erosión alrededor de plataformas de grúa y caminos internos",
         "mecanismo": "Escorrentía superficial concentrada",
         "efecto": "Restricción de maniobras de mantenimiento mayor",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Anegamiento de base de torre y armario de control",
         "mecanismo": "Drenaje insuficiente en la plataforma del aerogenerador",
         "efecto": "Fallas en el convertidor y disparos recurrentes",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Incremento de disparos por descargas atmosféricas",
         "mecanismo": "Actividad convectiva intensificada durante El Niño",
         "efecto": "Indisponibilidad intermitente y daño en punta de pala",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Pérdida de caminos internos y aislamiento de posiciones",
         "mecanismo": "Erosión y lodo en la red vial interna del parque",
         "efecto": "MTTR elevado e imposibilidad de movilizar grúa de gran porte",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Socavación de cimentaciones de aerogeneradores",
         "mecanismo": "Escorrentía concentrada y formación de cárcavas",
         "efecto": "Riesgo estructural y necesidad de inspección geotécnica",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Flujo de detritos sobre posiciones y red colectora de media tensión",
         "mecanismo": "Activación de quebradas dentro del área del parque",
         "efecto": "Pérdida de posiciones y de la red colectora",
         "desde": "critico", "criticidad": 5},
    ],
    "Subestación": [
        {"modo": "Obstrucción del drenaje perimetral por arrastre de sedimento",
         "mecanismo": "Escorrentía cargada de sólidos hacia el perímetro",
         "efecto": "Acumulación progresiva de agua en el patio de llaves",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Anegamiento de fosas de cables y canaletas",
         "mecanismo": "Infiltración y escorrentía que superan el drenaje de diseño",
         "efecto": "Degradación del aislamiento en cables de control y potencia",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Socavación y exposición de la malla de puesta a tierra",
         "mecanismo": "Erosión del terreno del patio por escorrentía",
         "efecto": "Aumento de la resistencia de puesta a tierra y riesgo de seguridad",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Flameo (flashover) en aisladores por humectación del depósito contaminante",
         "mecanismo": "Llovizna o neblina sobre capa salina o de polvo acumulado",
         "efecto": "Disparo de línea y desconexión forzada",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Ingreso de agua a casetas de control y tableros",
         "mecanismo": "Filtración por techos, pasamuros y canalizaciones",
         "efecto": "Indisponibilidad de protecciones y telecontrol",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Inundación del patio de llaves y pérdida de accesibilidad de maniobra",
         "mecanismo": "Lámina de agua que alcanza el nivel de equipos primarios",
         "efecto": "Desconexión preventiva de transformadores de potencia",
         "desde": "critico", "criticidad": 5},
    ],
    "Tramo de Línea de Transmisión": [
        {"modo": "Deslizamientos menores y caída de vegetación en la franja de servidumbre",
         "mecanismo": "Saturación del suelo en laderas de la franja",
         "efecto": "Riesgo de acercamiento y falla por contacto con conductores",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Erosión al pie de fundaciones de estructuras en ladera",
         "mecanismo": "Escorrentía concentrada sobre el terreno natural",
         "efecto": "Pérdida progresiva de capacidad portante de la fundación",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Pérdida de accesos y trochas de inspección",
         "mecanismo": "Lodo y formación de cárcavas en caminos de servicio",
         "efecto": "Incremento del MTTR ante cualquier falla del tramo",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Flameo por contaminación humectada en cadenas de aisladores",
         "mecanismo": "Lluvia ligera sobre depósito salino o de polvo",
         "efecto": "Salidas intempestivas de línea",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Inestabilidad de taludes bajo estructuras",
         "mecanismo": "Saturación prolongada del terreno de fundación",
         "efecto": "Intervención geotécnica de emergencia con línea fuera de servicio",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Socavación y volcamiento de torres en cruce de quebrada",
         "mecanismo": "Huaico que reactiva y profundiza el cauce",
         "efecto": "Colapso estructural e indisponibilidad prolongada del enlace",
         "desde": "critico", "criticidad": 5},
    ],
    "Saneamiento/Tratamiento de Agua": [
        {"modo": "Incremento de turbidez en la captación superficial",
         "mecanismo": "Arrastre de sólidos desde la cuenca aportante",
         "efecto": "Mayor dosificación de coagulante y menor caudal tratado",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Colmatación de desarenadores y presedimentadores",
         "mecanismo": "Carga sostenida de sedimento en el agua cruda",
         "efecto": "Purgas frecuentes y reducción de la capacidad de planta",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Acortamiento de las carreras de filtración",
         "mecanismo": "Alta carga de sólidos sobre los lechos filtrantes",
         "efecto": "Retrolavados frecuentes y pérdida de producción efectiva",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Turbidez por encima del límite de diseño de la planta",
         "mecanismo": "Pico de sólidos en suspensión en la fuente",
         "efecto": "Corte forzado del proceso de potabilización",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Anegamiento de cámaras de bombeo y salas eléctricas",
         "mecanismo": "Escorrentía pluvial que supera el drenaje del predio",
         "efecto": "Pérdida de impulsión y desabastecimiento del servicio",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Daño o pérdida de la obra de captación por huaico",
         "mecanismo": "Flujo de detritos de alta densidad en el cauce",
         "efecto": "Interrupción prolongada del servicio de agua potable",
         "desde": "critico", "criticidad": 5},
    ],
    "Infraestructura Industrial General": [
        {"modo": "Saturación del sistema de drenaje pluvial del predio",
         "mecanismo": "Escorrentía sobre techos, patios y áreas impermeables",
         "efecto": "Acumulación de agua en patios y vías internas",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Ingreso de agua a almacenes y áreas de proceso a nivel de piso",
         "mecanismo": "Lámina de agua superficial sobre el nivel de umbral",
         "efecto": "Daño a inventario y a equipos de baja altura de montaje",
         "desde": "bajo", "criticidad": 3},
        {"modo": "Deterioro de vías internas y de la logística de despacho",
         "mecanismo": "Erosión y lodo sobre la red vial del predio",
         "efecto": "Retrasos en recepción de insumos y despacho de producto",
         "desde": "bajo", "criticidad": 2},
        {"modo": "Inundación de subestación interna y salas eléctricas",
         "mecanismo": "Escorrentía que supera el umbral de las salas técnicas",
         "efecto": "Parada de proceso por pérdida de suministro eléctrico",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Pérdida de vías de acceso y aislamiento del predio",
         "mecanismo": "Corte de carreteras por inundación pluvial",
         "efecto": "Interrupción de suministros e imposibilidad de relevo de turno",
         "desde": "vigilancia", "criticidad": 4},
        {"modo": "Flujo de lodo (huaico) sobre el predio",
         "mecanismo": "Activación de quebrada adyacente a la instalación",
         "efecto": "Daño estructural y paralización prolongada de la operación",
         "desde": "critico", "criticidad": 5},
    ],
}


def mm_a_volumen_m3(lamina_mm, area_m2):
    """
    Identidad hidrológica básica:  1 mm de lluvia = 1 litro por m² = 0.001 m³/m².
        V (m³) = P (mm) × A (m²) / 1000
    """
    if lamina_mm is None or not np.isfinite(lamina_mm):
        return None
    return float(lamina_mm) * float(area_m2) / 1000.0


def estadisticos_ensamble(ensamble_mes):
    """Mediana y percentil 90 del total mensual entre los miembros del ensamble."""
    if ensamble_mes is None or ensamble_mes.empty:
        return None, None
    valores = ensamble_mes["total_mm"].to_numpy(dtype=float)
    valores = valores[np.isfinite(valores)]
    if valores.size == 0:
        return None, None
    return float(np.median(valores)), float(np.percentile(valores, 90))


def nivel_semaforo(probabilidad) -> str:
    """Traduce la probabilidad de excedencia del P90 (semáforo) al nivel del semáforo."""
    if probabilidad is None:
        return "bajo"
    if probabilidad >= UMBRAL_PROBABILIDAD_CRITICA:
        return "critico"
    if probabilidad >= UMBRAL_PROBABILIDAD_VIGILANCIA:
        return "vigilancia"
    return "bajo"


def modos_falla_dominantes(sector, nivel, maximo=3):
    """
    Devuelve los `maximo` modos de falla dominantes del sector para el nivel
    de semáforo vigente: se filtran los modos activos (su umbral de activación
    ya fue alcanzado) y se ordenan por criticidad descendente.
    """
    catalogo = MODOS_FALLA_LLUVIA.get(
        sector, MODOS_FALLA_LLUVIA["Infraestructura Industrial General"]
    )
    tope = NIVELES_ORDEN.get(nivel, 0)
    activos = [m for m in catalogo if NIVELES_ORDEN[m["desde"]] <= tope]
    activos.sort(key=lambda m: (-m["criticidad"], m["modo"]))
    return activos[:maximo]


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
                f"La probabilidad de superar el percentil {PERCENTIL_SEMAFORO} "
                f"({prob:.0f}%) aún no alcanza el umbral crítico del "
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

_SUSTITUCIONES_LATIN1 = {
    "—": "-", "–": "-", "−": "-", "“": '"', "”": '"', "‘": "'", "’": "'",
    "…": "...", "≥": ">=", "≤": "<=", "→": "->", "≈": "~", "•": "-",
}


def _latin1(texto: str) -> str:
    """fpdf2 con fuentes base usa Latin-1. Primero se reemplazan los signos
    tipográficos comunes (guion largo, comillas curvas, etc.) por su equivalente
    simple; antes salían como '?' en el PDF. Lo que quede fuera de rango se sanea."""
    for original, simple in _SUSTITUCIONES_LATIN1.items():
        texto = texto.replace(original, simple)
    return texto.encode("latin-1", "replace").decode("latin-1")


def _fmt(valor, decimales=1, sufijo=""):
    """Formatea un número para tablas; guion si falta el dato."""
    if valor is None:
        return "-"
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "-"
    if not np.isfinite(v):
        return "-"
    return f"{v:.{decimales}f}{sufijo}"


_COLOR_RELLENO_NIVEL = {"CRÍTICA": (228, 87, 46), "VIGILANCIA": (245, 184, 65),
                        "BAJA": (89, 201, 165)}


def _tabla_pdf(pdf, anchos, encabezados, filas):
    """Tabla simple con encabezado púrpura y filas alternadas.
    `filas` es una lista de listas de (texto, color_rgb_o_None)."""
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(112, 30, 99)  # Púrpura del logotipo
    pdf.set_text_color(255, 255, 255)
    for ancho, encabezado in zip(anchos, encabezados):
        pdf.cell(ancho, 7, _latin1(encabezado), border=1, align="C", fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8.5)
    for i, fila in enumerate(filas):
        if i % 2 == 0:
            pdf.set_fill_color(240, 244, 249)
        else:
            pdf.set_fill_color(255, 255, 255)
        for j, (ancho, (texto, color)) in enumerate(zip(anchos, fila)):
            pdf.set_text_color(*(color or (20, 20, 20)))
            pdf.set_font("Helvetica", "B" if (color and color != (120, 120, 120) and j > 0) else "", 8.5)
            pdf.cell(ancho, 6.2, _latin1(str(texto)), border=1,
                     align="L" if j == 0 else "C", fill=True)
        pdf.ln()
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "", 9)


def generar_pdf(contexto: dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # --- Encabezado corporativo ---
    pdf.set_fill_color(80, 22, 74)   # UP Púrpura
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
        ("Coordenadas del activo", f"Lat {contexto['lat']:.5f} / Lon {contexto['lon']:.5f}"),
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

    # --- 2. Resultado del mes evaluado ---
    sel = contexto.get("sel", {}) or {}
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("2. Resultado probabilístico del mes evaluado (lluvia mensual)"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    texto_ref = ""
    if sel.get("ref_nino_anio"):
        texto_ref = (f" Mismo mes en el Niño de referencia ({sel['ref_nino_anio']}): "
                     f"{_fmt(sel.get('ref_nino_mm'))} mm.")
    texto_pron = ""
    if sel.get("prob") is not None:
        texto_pron = (
            f" Pronóstico SEAS5 ({sel.get('n_miembros', 0)} miembros): mediana del ensamble "
            f"{_fmt(sel.get('mediana_ens'))} mm; P90 del ensamble {_fmt(sel.get('p90_ens'))} mm."
        )
    pdf.multi_cell(0, 5.5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
        f"Clima de referencia ERA5 1991-2020 en el punto: normal {_fmt(sel.get('normal'))} mm; "
        f"umbral de señal P{PERCENTIL_EXTREMO} {_fmt(sel.get('p80'))} mm; umbral del semáforo "
        f"P{PERCENTIL_SEMAFORO} {_fmt(sel.get('p90'))} mm.{texto_ref}{texto_pron}"
    ))
    prob = sel.get("prob")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, _latin1(f"Probabilidad de superar el P{PERCENTIL_SEMAFORO} (semáforo):"),
             new_x="LMARGIN", new_y="NEXT")
    x0, y0, ancho, alto = 12, pdf.get_y() + 1, 150, 9
    pdf.set_fill_color(225, 228, 233)
    pdf.rect(x0, y0, ancho, alto, "F")
    if prob is not None:
        nivel_pdf, _ = _nivel_amenaza_pdf(prob)
        pdf.set_fill_color(*_COLOR_RELLENO_NIVEL.get(nivel_pdf, (89, 201, 165)))
        pdf.rect(x0, y0, ancho * max(min(prob, 100), 0) / 100.0, alto, "F")
    pdf.set_xy(x0 + ancho + 4, y0 + 1.5)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 6, _latin1("n/d" if prob is None else f"{prob:.1f}%"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(y0 + alto + 2)
    pdf.set_font("Helvetica", "", 9)
    if prob is None:
        linea = "Mes fuera del horizonte actual de SEAS5: solo se dispone de la climatología."
    else:
        linea = (f"Señal de mes más lluvioso de lo habitual (> P{PERCENTIL_EXTREMO}): "
                 f"{_fmt(sel.get('prob_p80'))}%.")
        if sel.get("prob_ref") is not None:
            linea += (f"  Supera el mismo mes del Niño {sel.get('ref_nino_anio')}: "
                      f"{_fmt(sel.get('prob_ref'))}%.")
    pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_latin1(linea))
    pdf.ln(3)

    # --- 3. Panorama de la temporada: clima de referencia + pronóstico ---
    temporada = contexto.get("temporada", [])
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("3. Panorama mensual de la temporada (Oct 2026 - Abr 2027)"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, _latin1("3.a Clima de referencia en el punto (ERA5 1991-2020, mm/mes)"),
             new_x="LMARGIN", new_y="NEXT")
    filas_a = []
    for f in temporada:
        ref_txt = "-" if not f.get("ref_nino_anio") else f"{_fmt(f.get('ref_nino_mm'))} ({f['ref_nino_anio']})"
        filas_a.append([(f["mes"], None), (_fmt(f.get("normal")), None),
                        (_fmt(f.get("p80")), None), (_fmt(f.get("p90")), None),
                        (ref_txt, None)])
    _tabla_pdf(pdf, (40, 30, 30, 30, 60),
               ("Mes", "Normal", f"Señal P{PERCENTIL_EXTREMO}",
                f"Semáforo P{PERCENTIL_SEMAFORO}", "Mes Niño de referencia (año)"),
               filas_a)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, _latin1(f"3.b Pronóstico SEAS5 ({contexto.get('n_miembros', 51)} miembros) por mes"),
             new_x="LMARGIN", new_y="NEXT")
    filas_b = []
    for f in temporada:
        prob_mes = f.get("prob")
        if prob_mes is None:
            gris = (120, 120, 120)
            filas_b.append([(f["mes"], None)] + [("fuera de horizonte", gris)] + [("-", gris)] * 4)
            continue
        _, color_nivel = _nivel_amenaza_pdf(prob_mes)
        filas_b.append([
            (f["mes"], None),
            (_fmt(f.get("mediana_ens")), None),
            (_fmt(f.get("p90_ens")), None),
            (_fmt(f.get("prob_p80"), 0), None),
            (_fmt(prob_mes, 0), color_nivel),
            (_fmt(f.get("prob_ref"), 0), None),
        ])
    _tabla_pdf(pdf, (34, 30, 28, 30, 36, 32),
               ("Mes", "Mediana (mm)", "P90 ens. (mm)", f"> P{PERCENTIL_EXTREMO} (%)",
                f"> P{PERCENTIL_SEMAFORO} semáforo (%)", "> Niño ref. (%)"),
               filas_b)
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
        "Cada probabilidad es la fracción de miembros del ensamble SEAS5 cuyo total mensual supera "
        f"el umbral indicado del clima ERA5 1991-2020 en el punto del activo. P{PERCENTIL_EXTREMO}: lo "
        f"superan 2 de cada 10 años (señal de mes más lluvioso). P{PERCENTIL_SEMAFORO}: lo superan "
        "1 de cada 10 años (lluvia mensual fuerte; gobierna el semáforo). Niño ref.: mayor total "
        "observado en ese mes durante El Niño 1997-98 o El Niño Costero 2017. Mediana y P90 del "
        "ensamble: magnitud pronosticada en mm."
    ))
    pdf.ln(2)

    # --- Lectura mes a mes (misma narrativa que la app) ---
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 6, _latin1("Lectura mes a mes de la temporada:"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for color, encabezado, cuerpo in narrar_temporada_pdf(temporada):
        pdf.set_text_color(*color)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, _latin1(encabezado), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(40, 40, 40)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 4.6, new_x="LMARGIN", new_y="NEXT", text=_latin1(cuerpo))
        pdf.ln(1)
    nota = nota_lamina_baja(temporada)
    if nota:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(80, 22, 74)
        pdf.multi_cell(0, 4.6, new_x="LMARGIN", new_y="NEXT", text=_latin1("Nota: " + nota))
    pdf.set_text_color(90, 90, 90)
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
        f"Semáforo (probabilidad de superar el P{PERCENTIL_SEMAFORO}): CRÍTICA (>= "
        f"{UMBRAL_PROBABILIDAD_CRITICA:.0f}%)  |  VIGILANCIA ({UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}-"
        f"{UMBRAL_PROBABILIDAD_CRITICA:.0f}%)  |  BAJA (< {UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}%)."
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
        f"Umbrales: percentiles {PERCENTIL_EXTREMO} (señal) y {PERCENTIL_SEMAFORO} (semáforo) de la "
        "distribución empírica de totales mensuales ERA5 1991-2020 en el punto; probabilidad = fracción "
        "de miembros del ensamble que superan cada umbral. El P90 sigue el criterio SENAMHI/ENFEN de "
        "'lluvias fuertes', aplicado aquí al total mensual.",
        "Referencia Niño: total mensual ERA5 en el mismo mes de El Niño 1997-98 (oct 1997 - abr 1998) "
        "y de El Niño Costero 2017 (ene - abr 2017); se usa el mayor de ambos.",
    ]
    for ref in referencias:
        pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text= _latin1("- " + ref))
    pdf.ln(3)

    # --- 7. Diagnóstico de sesgo del modelo (uso técnico) ---
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1("7. Diagnóstico de sesgo del modelo en el punto (uso técnico)"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
        "Compara la normal mensual del propio SEAS5 (calculada por el ECMWF con sus pronósticos "
        "retrospectivos y obtenida como media del ensamble menos su anomalía) con la normal ERA5. "
        f"Una razón mayor a {RAZON_SESGO_HUMEDO:.1f} indica que el modelo es más lluvioso que el "
        "reanálisis en este punto, lo que infla las probabilidades de superar umbrales ERA5. "
        "Resultado orientativo; aún no se aplica corrección."
    ))
    diag = contexto.get("diagnostico") or []
    meta = contexto.get("diag_meta") or {}
    if diag:
        filas_d = []
        for f in diag:
            lectura = f.get("lectura", "")
            color = (200, 60, 30) if lectura == "modelo más húmedo" else (
                (40, 90, 170) if lectura == "modelo más seco" else None)
            filas_d.append([(f["mes"], None), (_fmt(f.get("normal_era5")), None),
                            (_fmt(f.get("normal_seas5")), None),
                            (_fmt(f.get("razon"), 2), color), (lectura, color)])
        _tabla_pdf(pdf, (40, 34, 38, 34, 44),
                   ("Mes", "Normal ERA5 (mm)", "Normal SEAS5 (mm)", "Razón SEAS5/ERA5", "Lectura"),
                   filas_d)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(90, 90, 90)
        factor = meta.get("factor")
        pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
            f"Unidad detectada del dato mensual de la API: {meta.get('unidad', '-')}"
            + ("" if factor is None else f" (relación con el total diario de los miembros: {factor:.2f}).")
        ))
        pdf.set_text_color(20, 20, 20)
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, new_x="LMARGIN", new_y="NEXT", text=_latin1(
            meta.get("mensaje") or "Diagnóstico no disponible para esta corrida."))
    pdf.ln(3)

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 4.5, new_x="LMARGIN", new_y="NEXT", text= _latin1(
        "Nota: los pronósticos estacionales son probabilísticos por naturaleza y aún no están "
        "corregidos por sesgo a escala local; representan una celda de ~36 km (SEAS5) frente a "
        "una de ~25 km (ERA5), que puede incluir laderas o mar además del sitio. Deben "
        "complementarse con el monitoreo oficial de SENAMHI/ENFEN antes de decisiones operativas."
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


def _num(v):
    """Float o None (acepta NaN/None)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _texto_mes(fila, md=False):
    """Narrativa de un mes, compartida por la pantalla (md=True) y el PDF.

    Devuelve (nivel, encabezado, cuerpo) con nivel en
    {"CRÍTICA", "VIGILANCIA", "BAJA", "SIN DATO"}.
    """
    b = (lambda t: f"**{t}**") if md else (lambda t: t)
    g = fila.get
    prob = _num(g("prob"))
    normal, p80, p90 = _num(g("normal")), _num(g("p80")), _num(g("p90"))
    nivel, _ = _nivel_amenaza_pdf(prob)
    n = g("n_miembros") or 51

    if prob is None:
        return nivel, f"{g('mes')} - sin dato aún", (
            "El mes todavía no entra en el horizonte de pronóstico de SEAS5 (~7 meses); por "
            f"ahora solo se muestra la climatología de referencia (normal {_fmt(normal)} mm; "
            f"P{PERCENTIL_SEMAFORO} {_fmt(p90)} mm)."
        )

    if nivel == "CRÍTICA":
        cuerpo = (
            f"{prob:.0f}% de los {n} escenarios superan el P{PERCENTIL_SEMAFORO} histórico "
            f"({_fmt(p90)} mm en el mes), un total que en 1991-2020 solo se alcanzó 1 de cada "
            f"10 años. {b('Amenaza CRÍTICA')} de lluvia mensual fuerte."
        )
    elif nivel == "VIGILANCIA":
        cuerpo = (
            f"{prob:.0f}% de los escenarios superan el P{PERCENTIL_SEMAFORO} ({_fmt(p90)} mm), "
            f"aún por debajo del umbral crítico ({UMBRAL_PROBABILIDAD_CRITICA:.0f}%). "
            f"Mes de {b('VIGILANCIA')}: conviene seguir de cerca los comunicados de ENFEN."
        )
    else:
        cuerpo = (
            f"Solo {prob:.0f}% de los escenarios superan el P{PERCENTIL_SEMAFORO} "
            f"({_fmt(p90)} mm). {b('Amenaza BAJA')} de lluvia mensual fuerte."
        )

    cuerpo += (
        f" Mediana pronosticada: {_fmt(g('mediana_ens'))} mm frente a una normal de "
        f"{_fmt(normal)} mm. Señal de mes más lluvioso de lo habitual (> P{PERCENTIL_EXTREMO}, "
        f"{_fmt(p80)} mm): {_fmt(g('prob_p80'), 0)}%."
    )
    if _num(g("prob_ref")) is not None and g("ref_nino_anio"):
        cuerpo += (f" Supera el mismo mes del Niño {g('ref_nino_anio')} "
                   f"({_fmt(g('ref_nino_mm'))} mm) en {_fmt(g('prob_ref'), 0)}% de los escenarios.")
    return nivel, f"{g('mes')} - {nivel} ({prob:.0f}%)", cuerpo


def nota_lamina_baja(temporada):
    """Una sola nota para los meses cuyo P90 es de pocos milímetros (clima muy seco)."""
    meses = [f["mes"].split(" ")[0].lower() for f in temporada
             if _num(f.get("p90")) is not None and _num(f.get("p90")) < LAMINA_REFERENCIA_BAJA_MM]
    if not meses:
        return None
    lista = meses[0] if len(meses) == 1 else ", ".join(meses[:-1]) + " y " + meses[-1]
    return (f"En {lista}, el P{PERCENTIL_SEMAFORO} de este punto equivale a menos de "
            f"{LAMINA_REFERENCIA_BAJA_MM:.0f} mm en todo el mes. En esos meses la señal describe "
            "un mes anómalo para un clima muy seco, no necesariamente lluvias intensas: conviene "
            "leer el porcentaje junto con la mediana pronosticada en milímetros.")


def narrar_temporada(df_temp):
    """Narrativa mes a mes para la pantalla (markdown con íconos del semáforo)."""
    iconos = {"CRÍTICA": "🔴", "VIGILANCIA": "🟠", "BAJA": "🟢", "SIN DATO": "⚪"}
    registros = df_temp.to_dict("records")
    lineas = []
    for fila in registros:
        nivel, encabezado, cuerpo = _texto_mes(fila, md=True)
        lineas.append(f"{iconos[nivel]} **{encabezado}.** {cuerpo}")
    nota = nota_lamina_baja(registros)
    if nota:
        lineas.append(f"ℹ️ _{nota}_")
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

    Devuelve tuplas (color_rgb, encabezado, cuerpo) con el mismo texto que la pantalla.
    """
    bloques = []
    for fila in temporada:
        nivel, encabezado, cuerpo = _texto_mes(fila, md=False)
        bloques.append((_nivel_amenaza_pdf(_num(fila.get("prob")))[1], encabezado, cuerpo))
    return bloques


# =============================================================================
# 7. INTERFAZ — BARRA LATERAL DE ENTRADAS
# =============================================================================

mostrar_logo(st.sidebar)
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

# El área se usa para traducir la lámina de lluvia (mm) a volumen (m³).
# La key depende del sector: al cambiar de sector, Streamlit reinstancia el
# widget y se recarga el valor por defecto de esa tipología de activo.
area_aporte = st.sidebar.number_input(
    "Área local de aporte (m²)",
    min_value=100, max_value=5_000_000,
    value=int(AREA_APORTE_DEFECTO.get(sector_usuario, 20_000)),
    step=1_000, key=f"area_aporte_{sector_usuario}",
    help="Huella local que capta lluvia: techos, patios, plataformas, canal, "
         "accesos y franja de servidumbre. NO usar áreas de escala cuenca: el "
         "pronóstico SEAS5 es puntual y no sostiene la hipótesis de lluvia "
         "uniforme sobre una cuenca completa.",
)

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
        "p90_mm":   [160, 190, 185, 95, 36, 13, 8, 10, 19, 45, 75, 125],
        "nino9798_mm": [np.nan] * 12,
        "nino2017_mm": [np.nan] * 12,
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

# ---- Cálculo probabilístico: toda la temporada en una sola pasada ----
# Cada fila resume un mes: clima ERA5 (normal, P80, P90, referencia Niño) y
# pronóstico SEAS5 (mediana y P90 del ensamble, probabilidades). Se calcula
# UNA vez y se reutiliza en gráficos, tablas, narrativa y PDF.
filas_temporada = [resumen_mes(df_miembros, climatologia, etq, a, m)
                   for etq, a, m in MESES_EVENTO]
df_temporada = pd.DataFrame(filas_temporada)
fila_sel = next(f for f in filas_temporada if f["mes"] == etiqueta_mes)

probabilidad = fila_sel["prob"]            # Semáforo: > P90
prob_p80_sel = fila_sel["prob_p80"]        # Señal: > P80
umbral_p80 = fila_sel["p80"]
umbral_p90 = fila_sel["p90"]
normal_mes = fila_sel["normal"]
ensamble_mes = _miembros_del_mes(df_miembros, anio_sel, mes_sel)
n_miembros = int(ensamble_mes["miembro"].nunique()) if not ensamble_mes.empty else 0

# Estadísticos del ensamble (gráfico de volumen de la Pestaña 3 y violín).
mediana_mes, p90_mes = fila_sel["mediana_ens"], fila_sel["p90_ens"]

# Diagnóstico de sesgo SEAS5 vs ERA5 (normal del modelo vs normal del reanálisis).
df_diag, meta_diag = diagnostico_sesgo(df_miembros, df_anom, climatologia)

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

    if not CARTO_KEY:
        st.info(
            "ℹ️ No se encontró `CARTO_KEY`, por lo que los mapas usan el fondo "
            "OpenStreetMap en lugar del mapa base oscuro. Para restaurar el fondo "
            "corporativo, añade la clave en `.streamlit/secrets.toml` (local) y en "
            "el panel *Secrets* de Streamlit Cloud (producción)."
        )

    st.caption(
        f"Mapa de calor: señal de anomalía de lluvia de SEAS5 para **{etiqueta_mes}** "
        "(índice donde 50 = normal climatológica). Tonos cian = más lluvioso de lo "
        "normal; tonos marrones = más seco. La probabilidad de excedencia rigurosa "
        "contra los umbrales P80 y P90 históricos está en la pestaña de Análisis Probabilístico, "
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
        "Shapely) y el círculo delimita el buffer de 10 km proyectado en UTM, coloreado "
        "según el índice de anomalía del mes en el punto de la planta."
    )

# ---------------------------------------------------------------- Pestaña 2
with tab_prob:
    if fuera_de_horizonte:
        st.subheader("Climatología de referencia (a la espera del horizonte SEAS5)")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Semáforo: prob. > P{PERCENTIL_SEMAFORO}", f"{probabilidad:.1f}%",
                  help=f"% de miembros del ensamble cuyo total mensual supera el percentil "
                       f"{PERCENTIL_SEMAFORO} histórico (lluvia mensual fuerte, 1 de cada 10 años)")
        m2.metric(f"Señal: prob. > P{PERCENTIL_EXTREMO}", f"{prob_p80_sel:.1f}%",
                  help=f"% de miembros por encima del percentil {PERCENTIL_EXTREMO} "
                       "(mes más lluvioso de lo habitual, 2 de cada 10 años)")
        m3.metric("Supera el mes Niño de referencia",
                  "—" if fila_sel["prob_ref"] is None else f"{fila_sel['prob_ref']:.1f}%",
                  help="% de miembros que superan el total observado en ese mes durante "
                       "El Niño 1997-98 o El Niño Costero 2017 (el mayor de ambos)")
        m4.metric("Miembros del ensamble", f"{n_miembros}")

        n1, n2, n3, n4 = st.columns(4)
        n1.metric("Normal climatológica", f"{normal_mes:.1f} mm")
        n2.metric(f"Umbral P{PERCENTIL_EXTREMO} / P{PERCENTIL_SEMAFORO}",
                  f"{umbral_p80:.1f} / {umbral_p90:.1f} mm")
        n3.metric("Mediana del ensamble", f"{mediana_mes:.1f} mm",
                  delta=f"{mediana_mes - normal_mes:+.1f} mm vs normal")
        n4.metric("Mes Niño de referencia",
                  "—" if not fila_sel["ref_nino_anio"]
                  else f"{fila_sel['ref_nino_mm']:.1f} mm ({fila_sel['ref_nino_anio']})")

        if aviso_ensamble:
            st.info("ℹ️ " + aviso_ensamble)

    # Curva de probabilidad a lo largo de toda la temporada crítica.
    fig_temp = go.Figure()
    fig_temp.add_trace(go.Bar(
        x=df_temporada["mes"], y=df_temporada["normal"],
        name="Normal climatológica (mm)", marker_color=COLOR_BARRA_NORMAL, opacity=0.8,
    ))
    con_mediana = df_temporada.dropna(subset=["mediana_ens"])
    fig_temp.add_trace(go.Bar(
        x=con_mediana["mes"], y=con_mediana["mediana_ens"],
        name="Mediana del ensamble (mm)", marker_color=COLOR_ACENTO, opacity=0.55,
    ))
    fig_temp.add_trace(go.Scatter(
        x=df_temporada["mes"], y=df_temporada["p90"],
        name=f"Umbral P{PERCENTIL_SEMAFORO} (mm)", mode="lines+markers",
        line=dict(color=COLOR_ADVERTENCIA, dash="dash"),
    ))
    con_prob = df_temporada.dropna(subset=["prob"])
    fig_temp.add_trace(go.Scatter(
        x=con_prob["mes"], y=con_prob["prob_p80"],
        name=f"Señal > P{PERCENTIL_EXTREMO} (%)", mode="lines+markers",
        line=dict(color=COLOR_TEXTO_TENUE, width=1.5, dash="dot"), yaxis="y2",
    ))
    fig_temp.add_trace(go.Scatter(
        x=con_prob["mes"], y=con_prob["prob"],
        name=f"Semáforo > P{PERCENTIL_SEMAFORO} (%)", mode="lines+markers+text",
        text=[f"{v:.0f}%" for v in con_prob["prob"]], textposition="top center",
        textfont=dict(color=COLOR_ACENTO),
        line=dict(color=COLOR_ACENTO, width=3), yaxis="y2",
    ))
    fig_temp.add_hline(y=UMBRAL_PROBABILIDAD_CRITICA, line_dash="dot",
                       line_color=COLOR_ALERTA, yref="y2",
                       annotation_text=f"Umbral crítico {UMBRAL_PROBABILIDAD_CRITICA:.0f}%",
                       annotation_font_color=COLOR_ALERTA)
    fig_temp.update_layout(
        template="plotly_dark", paper_bgcolor=COLOR_FONDO, plot_bgcolor=COLOR_LIENZO,
        height=490, barmode="group",
        title=dict(
            text="Temporada Oct 2026 – Abr 2027: clima de referencia, magnitud pronosticada y probabilidad",
            x=0.02, xanchor="left", y=0.97, yanchor="top",
            font=dict(color="#FFFFFF", size=15),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0,
                    font=dict(color=COLOR_TEXTO)),
        yaxis=dict(title="Precipitación mensual (mm)"),
        yaxis2=dict(title="Probabilidad (%)", overlaying="y", side="right",
                    range=[0, 105], showgrid=False),
        margin=dict(t=110, b=10, l=10, r=10),
    )
    estilo_grafico(fig_temp)
    st.plotly_chart(fig_temp, width='stretch')

    # --- Tabla completa de la temporada ---
    st.markdown("#### 📋 Tabla de la temporada")
    st.dataframe(pd.DataFrame({
        "Mes": df_temporada["mes"],
        "Normal (mm)": df_temporada["normal"].map(lambda v: _fmt(v)),
        f"P{PERCENTIL_EXTREMO} (mm)": df_temporada["p80"].map(lambda v: _fmt(v)),
        f"P{PERCENTIL_SEMAFORO} (mm)": df_temporada["p90"].map(lambda v: _fmt(v)),
        "Niño ref. (mm, año)": [
            "—" if not f["ref_nino_anio"] else f"{_fmt(f['ref_nino_mm'])} ({f['ref_nino_anio']})"
            for f in filas_temporada],
        "Mediana ens. (mm)": df_temporada["mediana_ens"].map(lambda v: _fmt(v)),
        "P90 ens. (mm)": df_temporada["p90_ens"].map(lambda v: _fmt(v)),
        f"> P{PERCENTIL_EXTREMO} (%)": df_temporada["prob_p80"].map(lambda v: _fmt(v, 0)),
        f"> P{PERCENTIL_SEMAFORO} semáforo (%)": df_temporada["prob"].map(lambda v: _fmt(v, 0)),
        "> Niño ref. (%)": df_temporada["prob_ref"].map(lambda v: _fmt(v, 0)),
    }), hide_index=True, width='stretch')

    # --- Lectura didáctica del gráfico, mes a mes ---
    st.markdown("#### 📖 Cómo leer este gráfico, mes a mes")
    st.markdown(
        f"La **línea gruesa** indica, para cada mes, qué porcentaje de los **51 escenarios** "
        f"del modelo SEAS5 supera el **P{PERCENTIL_SEMAFORO}** del clima 1991–2020 en el punto "
        f"(un total mensual que solo se alcanza 1 de cada 10 años). Esa línea gobierna el "
        f"semáforo: por encima de la **línea roja del {UMBRAL_PROBABILIDAD_CRITICA:.0f}%** el mes "
        f"es crítico. La **línea punteada fina** es la señal más débil (> P{PERCENTIL_EXTREMO}, "
        "mes más lluvioso de lo habitual). Las **barras** comparan la lluvia típica del mes con "
        "la **mediana pronosticada**: así se ve cuántos milímetros hay detrás de cada porcentaje."
    )
    for _linea in narrar_temporada(df_temporada):
        st.markdown(_linea)
    st.caption(
        f"Semáforo (probabilidad > P{PERCENTIL_SEMAFORO}): 🔴 crítico (≥ "
        f"{UMBRAL_PROBABILIDAD_CRITICA:.0f}%) · 🟠 vigilancia ({UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}–"
        f"{UMBRAL_PROBABILIDAD_CRITICA:.0f}%) · 🟢 bajo (< {UMBRAL_PROBABILIDAD_VIGILANCIA:.0f}%). "
        "Se interpreta como anomalía de área (~36 km), aún sin corrección de sesgo local, y no "
        "reemplaza los comunicados oficiales de ENFEN/SENAMHI."
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
    # ---------------------------------------------------------------------
    # A. Modos de falla dominantes del sector para el nivel del mes
    # ---------------------------------------------------------------------
    nivel_mes = nivel_semaforo(probabilidad)
    es_escenario_seco = "Sequía" in titulo_riesgo

    st.markdown("#### 🔧 Modos de falla dominantes para este sector y este mes")
    st.markdown(
        f"Sector **{sector_usuario}** · {etiqueta_mes} · nivel de amenaza "
        f"**{ETIQUETA_NIVEL[nivel_mes]}**. El catálogo de modos de falla es fijo por "
        "sector; lo que cambia con el nivel del mes es qué modos se vuelven creíbles "
        "y cuál domina. Al subir el semáforo, los modos crónicos ceden el primer "
        "lugar a los modos de evento."
    )

    if es_escenario_seco:
        st.info(
            "ℹ️ El mes evaluado cae en el escenario de **déficit de precipitación** "
            "(Sierra Sur / Altiplano). El catálogo de modos de falla que se lista "
            "abajo corresponde a la amenaza de **lluvia extrema**; para la condición "
            "seca aplica la evaluación del panel superior. El catálogo de modos de "
            "falla por sequía es el siguiente incremento de la herramienta."
        )

    modos = modos_falla_dominantes(sector_usuario, nivel_mes, maximo=3)
    st.dataframe(pd.DataFrame([{
        "#": i + 1,
        "Modo de falla": m["modo"],
        "Mecanismo físico": m["mecanismo"],
        "Efecto operativo": m["efecto"],
        "Criticidad": "●" * int(m["criticidad"]),
        "Activo desde": ETIQUETA_NIVEL[m["desde"]],
    } for i, m in enumerate(modos)]), hide_index=True, width='stretch')
    st.caption(
        "Catálogo paramétrico por tipología de activo (amenaza: lluvia extrema). "
        "Los umbrales de activación y la criticidad relativa deben calibrarse con "
        "el historial de fallas y el contexto operacional de cada planta; esta "
        "tabla es el punto de partida estructurado, no el resultado de un análisis "
        "RCM específico de la instalación."
    )

    # ---------------------------------------------------------------------
    # B. Traducción de lámina de lluvia (mm) a volumen (m³) sobre el activo
    # ---------------------------------------------------------------------
    st.markdown("#### 💧 De milímetros a metros cúbicos: el volumen sobre tu activo")
    st.markdown(
        "La lluvia se mide como lámina: **1 mm equivale a 1 litro por cada m²**, "
        "es decir 0.001 m³/m². Multiplicada por el área local de aporte configurada "
        "en la barra lateral, esa lámina se convierte en el volumen de agua que el "
        "sistema de drenaje debe evacuar:  **V (m³) = P (mm) × A (m²) / 1000**."
    )

    barras = [
        ("Normal climatológica", normal_mes, COLOR_BARRA_NORMAL, "referencia"),
        (f"Umbral P{PERCENTIL_SEMAFORO} histórico", umbral_p90, COLOR_ADVERTENCIA, "referencia"),
        ("Mediana del ensamble", mediana_mes, COLOR_ACENTO, "pronóstico"),
        ("P90 del ensamble", p90_mes, COLOR_ALERTA, "pronóstico"),
    ]
    barras = [b for b in barras if b[1] is not None and np.isfinite(b[1])]

    if len(barras) < 2:
        st.info(
            "El gráfico comparativo de volumen se habilitará cuando el mes "
            "seleccionado entre en el horizonte de pronóstico de SEAS5. Mientras "
            "tanto solo se dispone de la climatología de referencia."
        )
    else:
        etiquetas = [b[0] for b in barras]
        laminas = [float(b[1]) for b in barras]
        volumenes = [mm_a_volumen_m3(b[1], area_aporte) for b in barras]
        colores = [b[2] for b in barras]

        fig_vol = go.Figure()
        fig_vol.add_trace(go.Bar(
            x=etiquetas, y=volumenes,
            marker_color=colores,
            text=[f"{v:,.0f} m³<br>({p:.0f} mm)" for v, p in zip(volumenes, laminas)],
            textposition="outside",
            textfont=dict(color=COLOR_TEXTO, size=12),
            hovertemplate="%{x}<br>%{y:,.0f} m³<extra></extra>",
        ))
        fig_vol.update_layout(
            template="plotly_dark", paper_bgcolor=COLOR_FONDO, plot_bgcolor=COLOR_LIENZO,
            height=430, showlegend=False,
            title=dict(
                text=(f"Volumen acumulado mensual sobre {area_aporte:,.0f} m² — "
                      f"{etiqueta_mes}"),
                x=0.02, xanchor="left", y=0.97, yanchor="top",
                font=dict(color="#FFFFFF", size=15),
            ),
            yaxis=dict(title="Volumen acumulado del mes (m³)"),
            margin=dict(t=80, b=10, l=10, r=10),
        )
        # Holgura superior para que las etiquetas "outside" no se recorten.
        fig_vol.update_yaxes(range=[0, max(volumenes) * 1.28])
        estilo_grafico(fig_vol)
        st.plotly_chart(fig_vol, width='stretch')

        # Lectura cuantificada del salto entre el clima normal y el pronóstico alto.
        vol_normal = mm_a_volumen_m3(normal_mes, area_aporte)
        if p90_mes is not None and vol_normal:
            vol_p90 = mm_a_volumen_m3(p90_mes, area_aporte)
            exceso = vol_p90 - vol_normal
            veces = vol_p90 / vol_normal if vol_normal > 0 else float("nan")
            v1, v2, v3 = st.columns(3)
            v1.metric("Volumen en condición normal", f"{vol_normal:,.0f} m³")
            v2.metric("Volumen en el escenario P90", f"{vol_p90:,.0f} m³",
                      delta=f"{exceso:+,.0f} m³")
            v3.metric("Factor sobre lo normal",
                      "—" if not np.isfinite(veces) else f"{veces:.1f}×")

        st.caption(
            f"Las dos primeras barras son **referencia histórica** (ERA5 1991–2020) y "
            f"las dos últimas son **pronóstico** (ensamble SEAS5 de {n_miembros} "
            f"miembros para {etiqueta_mes}). El **P90 del ensamble** no es la lluvia "
            "máxima posible: es el valor que solo el 10 % de los miembros supera. "
            "Todas las cifras son **acumulados mensuales**, de modo que responden a "
            "cuánta agua cae en el mes, no a si el drenaje se desborda en un evento: "
            "eso depende del máximo diario, que se resuelve con estadística de eventos "
            "a resolución diaria. El volumen se calcula sobre el área local de aporte "
            "declarada por el usuario y supone lluvia uniforme sobre ella."
        )

    # ---------------------------------------------------------------------
    # C. Trazabilidad de la evaluación
    # ---------------------------------------------------------------------
    st.markdown("#### Parámetros que activaron esta evaluación")
    st.dataframe(pd.DataFrame({
        "Parámetro": ["Departamento", "Grupo climático", "Sector", "Mes",
                      f"Probabilidad > P{PERCENTIL_SEMAFORO} (semáforo)",
                      f"Probabilidad > P{PERCENTIL_EXTREMO} (señal)", "Nivel de semáforo",
                      "Área local de aporte",
                      "Anomalía SEAS5 (mm/día)", "Umbral crítico configurado"],
        "Valor": [dep_nombre, grupo, sector_usuario, etiqueta_mes,
                  "—" if probabilidad is None else f"{probabilidad:.1f}%",
                  "—" if prob_p80_sel is None else f"{prob_p80_sel:.1f}%",
                  ETIQUETA_NIVEL[nivel_mes],
                  f"{area_aporte:,.0f} m²",
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
            fillcolor="rgba(223,160,214,0.22)", line_color=COLOR_ACENTO,
            marker=dict(size=5, color="#F0CDEA"),
            name=f"{n_miembros} miembros",
        ))
        fig_violin.add_hline(y=umbral_p90, line_dash="dash", line_color=COLOR_ALERTA,
                             annotation_text=f"P{PERCENTIL_SEMAFORO} histórico = {umbral_p90:.1f} mm",
                             annotation_font_color=COLOR_ALERTA)
        fig_violin.add_hline(y=umbral_p80, line_dash="dash", line_color=COLOR_ADVERTENCIA,
                             annotation_text=f"P{PERCENTIL_EXTREMO} histórico = {umbral_p80:.1f} mm",
                             annotation_position="bottom right",
                             annotation_font_color=COLOR_ADVERTENCIA)
        if fila_sel["ref_nino_anio"]:
            fig_violin.add_hline(y=fila_sel["ref_nino_mm"], line_dash="longdash",
                                 line_color="#7FB3FF",
                                 annotation_text=(f"Niño {fila_sel['ref_nino_anio']} = "
                                                  f"{fila_sel['ref_nino_mm']:.1f} mm"),
                                 annotation_position="top left",
                                 annotation_font_color="#7FB3FF")
        fig_violin.add_hline(y=normal_mes, line_dash="dot", line_color=COLOR_OK,
                             annotation_text=f"Normal = {normal_mes:.0f} mm",
                             annotation_font_color=COLOR_OK)
        fig_violin.update_layout(
            template="plotly_dark", paper_bgcolor=COLOR_FONDO, plot_bgcolor=COLOR_LIENZO,
            height=460, yaxis_title="Precipitación mensual total (mm)",
            showlegend=False, margin=dict(t=30),
        )
        estilo_grafico(fig_violin)
        st.plotly_chart(fig_violin, width='stretch')
        st.markdown(f"""
**Cómo leer este gráfico (violín de distribución):**

- **Cada punto es un miembro del ensamble** — una de las {n_miembros} simulaciones
que el ECMWF corre partiendo de condiciones atmosféricas iniciales ligeramente distintas.
Juntos representan los futuros físicamente plausibles para {etiqueta_mes}.
- **El ancho del violín** en cada altura indica cuántos miembros predicen ese nivel de
lluvia: donde es más ancho, más probable; donde es angosto, menos probable. *La forma
ES la distribución de probabilidad.*
- **La caja central** marca el rango intercuartílico (del 25 % al 75 % de los miembros) y
la línea de la media; resume dónde se concentra el pronóstico.
- **Línea roja punteada (P{PERCENTIL_SEMAFORO} = {umbral_p90:.1f} mm):** el total mensual que
en 30 años de ERA5 solo se superó 1 de cada 10 años. **La probabilidad del semáforo es
simplemente qué fracción de los puntos cae por encima de esta línea.**
- **Línea ámbar punteada (P{PERCENTIL_EXTREMO} = {umbral_p80:.1f} mm):** señal más débil, mes
más lluvioso de lo habitual (2 de cada 10 años).
- **Línea azul (si aparece):** total observado en ese mismo mes durante El Niño 1997-98 o
El Niño Costero 2017, como referencia de lo que ya ocurrió.
- **Línea verde punteada (Normal = {normal_mes:.0f} mm):** la lluvia típica del mes.

En términos operativos: mientras más masa del violín quede **por encima** de la línea roja,
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
píxel del activo. Se usan dos umbrales de la distribución empírica de 30 años de cada mes:
el **percentil {PERCENTIL_EXTREMO}** como *señal* de mes más lluvioso de lo habitual y el
**percentil {PERCENTIL_SEMAFORO}** como umbral del *semáforo* (lluvia mensual fuerte; el
SENAMHI/ENFEN usa el P90 para "lluvias fuertes" a escala diaria). Como referencia histórica
se muestra el total del mismo mes en El Niño 1997-98 y El Niño Costero 2017.

**3. Pronóstico estacional.** **ECMWF SEAS5**, sistema operativo de **51 miembros**
(resolución ~36 km, actualización mensual el día 5, horizonte 7 meses), distribuido como
dato abierto a través de la Seasonal Forecast API de Open-Meteo. La probabilidad reportada
es la **frecuencia relativa de excedencia** del umbral dentro del ensamble:
`P = #(miembros > umbral) / N × 100`, calculada para el P{PERCENTIL_EXTREMO}, el
P{PERCENTIL_SEMAFORO} y la referencia Niño. Se reporta además la **mediana y el P90 del
ensamble en mm**, para que cada porcentaje vaya acompañado de su magnitud.

**4. Contexto de escenarios.** Los modelos globales **CMIP6** del IPCC y sus trayectorias
SSP enmarcan la no-estacionariedad del clima: la variabilidad ENOS se superpone al
calentamiento antropogénico, por lo que la climatología histórica se usa como referencia
de umbral y no como pronóstico.

**5. Limitaciones declaradas.** SEAS5 aún no está corregido por sesgo a escala local
(interpretar como anomalía de área); el diagnóstico de sesgo de esta pestaña muestra cuánto
difiere la normal del modelo de la de ERA5 en el punto. Los meses tardíos del verano entran
al horizonte progresivamente;
la matriz de consecuencias es paramétrica (región × sector) y debe calibrarse con las
curvas de daño específicas de cada planta.

**6. Geoespacial.** Límites ADM1 de **geoBoundaries** (licencia abierta), intersección
punto-en-polígono con Shapely/GEOS y buffer métrico en proyección UTM local.
""")

    st.subheader("🧪 Diagnóstico de sesgo del modelo en el punto")
    st.markdown(
        "Compara la **normal mensual del propio SEAS5** (calculada por el ECMWF con sus "
        "pronósticos retrospectivos: media del ensamble menos su anomalía) con la **normal "
        "ERA5** del punto. Si el modelo \"cree\" que el lugar es más lluvioso de lo que registra "
        f"el reanálisis (razón > {RAZON_SESGO_HUMEDO:.1f}), las probabilidades de superar "
        "umbrales ERA5 quedan infladas, sobre todo en la costa hiperárida, donde los umbrales "
        "son de pocos milímetros. Todavía **no se aplica corrección**: este cuadro sirve para "
        "decidir si hace falta y de qué tamaño."
    )
    if df_diag.empty:
        st.info("ℹ️ " + (meta_diag.get("mensaje") or "Diagnóstico no disponible para esta corrida."))
    else:
        st.dataframe(pd.DataFrame({
            "Mes": df_diag["mes"],
            "Normal ERA5 (mm)": df_diag["normal_era5"].map(lambda v: _fmt(v)),
            "Normal SEAS5 (mm)": df_diag["normal_seas5"].map(lambda v: _fmt(v)),
            "Razón SEAS5/ERA5": df_diag["razon"].map(lambda v: _fmt(v, 2)),
            "Lectura": df_diag["lectura"],
        }), hide_index=True, width='stretch')
        st.caption(
            f"Unidad detectada del dato mensual de la API: **{meta_diag.get('unidad')}** "
            f"(relación con el total de los miembros diarios: {meta_diag.get('factor', 0):.2f}; "
            "≈ días del mes indica mm/día, ≈ 1 indica mm/mes). Lectura orientativa: "
            f"> {RAZON_SESGO_HUMEDO:.1f} modelo más húmedo · < {RAZON_SESGO_SECO:.2f} modelo más "
            "seco · intermedio consistente."
        )

    st.subheader("📄 Reporte ejecutivo descargable")
    if fuera_de_horizonte:
        st.caption("El PDF incluirá la climatología y el contexto ENFEN; la probabilidad "
                   "se reportará como no disponible para este mes.")
    contexto_pdf = {
        "lat": lat_usuario, "lon": lon_usuario, "departamento": dep_nombre,
        "sector": sector_usuario, "mes_etiqueta": etiqueta_mes,
        "modo_datos": modo_datos,
        "n_miembros": n_miembros if n_miembros else 51,
        "sel": fila_sel,
        "riesgo_titulo": titulo_riesgo, "riesgo_mensaje": mensaje_riesgo,
        "temporada": filas_temporada,
        "diagnostico": df_diag.to_dict("records") if not df_diag.empty else [],
        "diag_meta": meta_diag,
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
