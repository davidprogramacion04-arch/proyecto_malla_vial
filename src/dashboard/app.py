"""
Dashboard Interactivo de PercepciÃ³n Ciudadana sobre la Malla Vial de BogotÃ¡
Desarrollado con Streamlit y Plotly.
"""

import os
import sys
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

# ConfiguraciÃ³n de pÃ¡gina
st.set_page_config(
    page_title="Malla Vial BogotÃ¡ - PercepciÃ³n Ciudadana",
    page_icon="ðŸš§",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS personalizados
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        color: #1E88E5;
        font-weight: 700;
        margin-bottom: 0px;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #555555;
        margin-bottom: 20px;
    }
    .metric-card {
        background-color: #F8F9FA;
        border-left: 5px solid #1E88E5;
        padding: 15px;
        border-radius: 5px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .sentiment-neg {
        color: #E53935;
        font-weight: bold;
    }
    .sentiment-neu {
        color: #FB8C00;
        font-weight: bold;
    }
    .sentiment-pos {
        color: #43A047;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Cargar Datos
@st.cache_data
def cargar_datos():
    base_dir = Path(__file__).resolve().parents[2]
    
    path_sentimientos = base_dir / "data" / "twitter" / "modelos_twitter" / "comentarios_sentimiento.csv"
    path_entidades = base_dir / "data" / "twitter" / "modelos_twitter" / "resumen_percepcion_por_entidad.csv"
    path_noticias = base_dir / "data" / "noticias" / "scraping_noticias" / "noticias_limpias.csv"
    path_sentimiento_noticias = base_dir / "data" / "noticias" / "scraping_noticias" / "noticias_contenido_candidatas.csv"
    
    if not path_sentimientos.exists():
        st.error(f"No se encontrÃ³ el archivo de datos: {path_sentimientos}")
        return None, None, None
        
    df_comentarios = pd.read_csv(path_sentimientos)
    
    if path_entidades.exists():
        df_entidades = pd.read_csv(path_entidades)
    else:
        df_entidades = None
        
    if path_noticias.exists():
        df_noticias = pd.read_csv(path_noticias)
    else:
        df_noticias = None

    # Unir el sentimiento calculado sobre el texto extraÃ­do con los metadatos RSS.
    if df_noticias is not None and path_sentimiento_noticias.exists():
        df_sent_noticias = pd.read_csv(path_sentimiento_noticias)
        cols_sent = [c for c in ["id_registro", "sentimiento_codigo", "confianza_sentimiento_codigo", "estado_sentimiento_codigo", "url_original"] if c in df_sent_noticias.columns]
        df_noticias = df_noticias.merge(
            df_sent_noticias[cols_sent].drop_duplicates("id_registro"),
            on="id_registro", how="left",
        )
        etiquetas = {"NEG": "NEGATIVO", "NEU": "NEUTRO", "POS": "POSITIVO"}
        if "sentimiento_codigo" in df_noticias.columns:
            df_noticias["sentimiento_etiqueta_noticia"] = df_noticias["sentimiento_codigo"].map(etiquetas)
        
    # Tratamiento de fechas
    if 'fecha_publicacion' in df_comentarios.columns:
        df_comentarios['fecha_dt'] = pd.to_datetime(df_comentarios['fecha_publicacion'], errors='coerce')
        df_comentarios['fecha_corta'] = df_comentarios['fecha_dt'].dt.strftime('%Y-%m-%d')
        
    if df_noticias is not None and 'fecha_publicacion_estandarizada' in df_noticias.columns:
        df_noticias['fecha_dt'] = pd.to_datetime(df_noticias['fecha_publicacion_estandarizada'], errors='coerce')
        df_noticias['fecha_corta'] = df_noticias['fecha_dt'].dt.strftime('%Y-%m-%d')
    
    return df_comentarios, df_entidades, df_noticias

df_comentarios, df_entidades, df_noticias = cargar_datos()

if df_comentarios is not None:
    # Sidebar Filters
    st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/thumb/8/8c/Escudo_de_Bogot%C3%A1.svg/1200px-Escudo_de_Bogot%C3%A1.svg.png", width=80)
    st.sidebar.title("Filtros del Sistema")
    st.sidebar.markdown("---")
    
    # Filtro por Sentimiento
    sentimientos_disp = ["TODOS"] + list(df_comentarios['sentimiento_etiqueta'].dropna().unique())
    sentimiento_sel = st.sidebar.selectbox("Seleccionar Sentimiento (Twitter):", sentimientos_disp)
    
    # Filtro por Candidato Vial (Filtro de relevancia)
    candidato_disp = ["Solo Relevantes Malla Vial", "Todos los Registros"]
    candidato_sel = st.sidebar.radio("Filtro Relevancia Vial:", candidato_disp)
    
    # Filtro BÃºsqueda Texto
    busqueda_texto = st.sidebar.text_input("ðŸ” Buscar tÃ©rmino (ej. hueco, bache, GalÃ¡n):", "")
    
    # Aplicar Filtros al Dataframe Twitter
    df_filtrado = df_comentarios.copy()
    if candidato_sel == "Solo Relevantes Malla Vial":
        df_filtrado = df_filtrado[df_filtrado['es_candidato_vial'] == True]
    if sentimiento_sel != "TODOS":
        df_filtrado = df_filtrado[df_filtrado['sentimiento_etiqueta'] == sentimiento_sel]
    if busqueda_texto.strip() != "":
        df_filtrado = df_filtrado[df_filtrado['texto_limpio'].str.contains(busqueda_texto, case=False, na=False)]
        
    # Aplicar Filtros al Dataframe Noticias
    df_noticias_filtrado = df_noticias.copy() if df_noticias is not None else pd.DataFrame()
    if not df_noticias_filtrado.empty:
        if candidato_sel == "Solo Relevantes Malla Vial" and 'es_candidata_vial_preliminar' in df_noticias_filtrado.columns:
            df_noticias_filtrado = df_noticias_filtrado[df_noticias_filtrado['es_candidata_vial_preliminar'] == True]
        if busqueda_texto.strip() != "" and 'titulo_limpio' in df_noticias_filtrado.columns:
            df_noticias_filtrado = df_noticias_filtrado[df_noticias_filtrado['titulo_limpio'].str.contains(busqueda_texto, case=False, na=False)]

    # --- CABECERA ---
    st.markdown('<div class="main-header">ðŸš§ Tablero de Control: PercepciÃ³n Vial BogotÃ¡</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Monitoreo multinivel: Redes Sociales (Twitter/X) vs Prensa Digital (Google News)</div>', unsafe_allow_html=True)
    
    # --- METRICAS CLAVE (KPIs) ---
    col1, col2, col3, col4 = st.columns(4)
    
    total_tweets = len(df_filtrado)
    total_news = len(df_noticias_filtrado)
    pct_negativo = (df_filtrado['sentimiento_etiqueta'] == 'NEGATIVO').mean() * 100 if total_tweets > 0 else 0
    pct_positivo = (df_filtrado['sentimiento_etiqueta'] == 'POSITIVO').mean() * 100 if total_tweets > 0 else 0
    
    with col1:
        st.metric("Comentarios X (Twitter)", f"{total_tweets}")
    with col2:
        st.metric("Noticias de Prensa (Google)", f"{total_news}")
    with col3:
        st.metric("PercepciÃ³n Negativa Twitter ðŸ˜¡", f"{pct_negativo:.1f}%", delta=f"{pct_negativo:.1f}%", delta_color="inverse")
    with col4:
        st.metric("PercepciÃ³n Positiva Twitter ðŸ˜ƒ", f"{pct_positivo:.1f}%")
        
    st.markdown("---")
    
    # --- PESTAÃ‘AS PRINCIPALES ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "ðŸ“Š DistribuciÃ³n Sentimiento", 
        "ðŸ“° Prensa Google News", 
        "ðŸ›ï¸ AnÃ¡lisis por Entidad", 
        "ðŸ“… EvoluciÃ³n Temporal", 
        "ðŸ” Explorador Twitter"
    ])
    
    with tab1:
        st.subheader("DistribuciÃ³n General del Sentimiento Ciudadano en Twitter")
        
        c1, c2 = st.columns([1, 1])
        
        with c1:
            sent_counts = df_filtrado['sentimiento_etiqueta'].value_counts().reset_index()
            sent_counts.columns = ['Sentimiento', 'Cantidad']
            
            fig_pie = px.pie(
                sent_counts, 
                names='Sentimiento', 
                values='Cantidad',
                color='Sentimiento',
                color_discrete_map={'NEGATIVO': '#E53935', 'NEUTRO': '#FB8C00', 'POSITIVO': '#43A047'},
                hole=0.45,
                title="ProporciÃ³n de Sentimiento (RoBERTuito)"
            )
            fig_pie.update_traces(textinfo='percent+label')
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with c2:
            fig_bar = px.bar(
                sent_counts,
                x='Sentimiento',
                y='Cantidad',
                color='Sentimiento',
                color_discrete_map={'NEGATIVO': '#E53935', 'NEUTRO': '#FB8C00', 'POSITIVO': '#43A047'},
                text='Cantidad',
                title="Volumen Absoluto de Comentarios"
            )
            fig_bar.update_layout(showlegend=False)
            st.plotly_chart(fig_bar, use_container_width=True)
            
        # Top tÃ©rminos detectados
        st.markdown("#### ðŸ·ï¸ TÃ©rminos Frecuentes Relacionados con Deterioro Vial")
        all_terms = []
        for term_str in df_filtrado['terminos_deterioro_detectados'].dropna():
            try:
                eval_list = eval(term_str)
                all_terms.extend(eval_list)
            except:
                pass
                
        if all_terms:
            df_terms = pd.DataFrame(pd.Series(all_terms).value_counts().reset_index())
            df_terms.columns = ['TÃ©rmino / Palabra Clave', 'Frecuencia']
            
            fig_terms = px.bar(
                df_terms.head(10),
                x='Frecuencia',
                y='TÃ©rmino / Palabra Clave',
                orientation='h',
                color='Frecuencia',
                color_continuous_scale='Reds',
                title="Top 10 Palabras Clave de Deterioro Detectadas en Twitter"
            )
            fig_terms.update_layout(yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig_terms, use_container_width=True)

    with tab2:
        st.subheader("ðŸ“° AnÃ¡lisis de Cobertura en Medios de Prensa (Google News)")
        st.write(f"Se identificaron **{len(df_noticias_filtrado)}** titulares y artÃ­culos sobre la malla vial de BogotÃ¡ recopilados vÃ­a Google News.")
        
        noticias_analizadas = df_noticias_filtrado[
            df_noticias_filtrado.get("estado_sentimiento_codigo", pd.Series(index=df_noticias_filtrado.index, dtype=object)) == "analizado"
        ].copy()
        st.markdown("#### Sentimiento del contenido de las noticias")
        st.caption("El modelo clasifica el tono del texto extraÃ­do de cada artÃ­culo; no mide directamente la opiniÃ³n del medio ni de la ciudadanÃ­a.")
        if not noticias_analizadas.empty:
            cn_sent1, cn_sent2 = st.columns(2)
            conteo_sent_noticias = noticias_analizadas["sentimiento_etiqueta_noticia"].value_counts().reindex(
                ["NEGATIVO", "NEUTRO", "POSITIVO"], fill_value=0
            ).rename_axis("Sentimiento").reset_index(name="Noticias")
            colores_sent = {"NEGATIVO": "#E53935", "NEUTRO": "#FB8C00", "POSITIVO": "#43A047"}
            with cn_sent1:
                fig_sent_noticias = px.pie(
                    conteo_sent_noticias, names="Sentimiento", values="Noticias",
                    color="Sentimiento", color_discrete_map=colores_sent, hole=0.45,
                    title="DistribuciÃ³n del sentimiento (RoBERTuito)",
                )
                fig_sent_noticias.update_traces(textinfo="percent+label")
                st.plotly_chart(fig_sent_noticias, use_container_width=True)
            with cn_sent2:
                fig_conf_noticias = px.box(
                    noticias_analizadas, x="sentimiento_etiqueta_noticia",
                    y="confianza_sentimiento_codigo", color="sentimiento_etiqueta_noticia",
                    color_discrete_map=colores_sent,
                    labels={"sentimiento_etiqueta_noticia": "Sentimiento", "confianza_sentimiento_codigo": "Confianza"},
                    title="Confianza del modelo por sentimiento",
                )
                st.plotly_chart(fig_conf_noticias, use_container_width=True)
            st.caption(f"ArtÃ­culos analizados: {len(noticias_analizadas)} de {len(df_noticias_filtrado)} en el filtro actual.")
        else:
            st.info("No hay noticias con texto analizado para los filtros seleccionados. Ejecuta src/modelos/01_analizar_sentimiento_noticias.py para generarlo.")

        if not df_noticias_filtrado.empty:
            cn1, cn2 = st.columns([1, 1])
            
            with cn1:
                # Extraer medio o fuente de prensa si existe
                df_noticias_filtrado['Medio'] = df_noticias_filtrado['titulo'].apply(lambda x: str(x).split(' - ')[-1] if ' - ' in str(x) else 'Otros')
                top_medios = df_noticias_filtrado['Medio'].value_counts().head(10).reset_index()
                top_medios.columns = ['Medio de ComunicaciÃ³n', 'ArtÃ­culos Publicados']
                
                fig_medios = px.bar(
                    top_medios,
                    x='ArtÃ­culos Publicados',
                    y='Medio de ComunicaciÃ³n',
                    orientation='h',
                    color='ArtÃ­culos Publicados',
                    color_continuous_scale='Blues',
                    title="Principales Medios que Reportan la Malla Vial"
                )
                fig_medios.update_layout(yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig_medios, use_container_width=True)
                
            with cn2:
                # DistribuciÃ³n del score de relevancia en noticias
                fig_score = px.histogram(
                    df_noticias_filtrado,
                    x='score_relevancia_preliminar',
                    nbins=5,
                    title="DistribuciÃ³n del Score de Relevancia Vial (Noticias)",
                    labels={'score_relevancia_preliminar': 'Score de Relevancia (0 a 5)'},
                    color_discrete_sequence=['#1E88E5']
                )
                st.plotly_chart(fig_score, use_container_width=True)
                
            st.markdown("#### ðŸ“‹ Listado de Noticias y Reportajes")
            cols_noticias = ['titulo_limpio', 'fecha_publicacion_estandarizada', 'score_relevancia_preliminar', 'sentimiento_etiqueta_noticia', 'confianza_sentimiento_codigo', 'motivos_relevancia_preliminar', 'url']
            cols_exist_noticias = [c for c in cols_noticias if c in df_noticias_filtrado.columns]
            
            st.dataframe(
                df_noticias_filtrado[cols_exist_noticias],
                column_config={
                    "url": st.column_config.LinkColumn("Ver Noticia Original"),
                    "score_relevancia_preliminar": st.column_config.NumberColumn("Relevancia Vial"),
                    "confianza_sentimiento_codigo": st.column_config.NumberColumn("Confianza sentimiento", format="%.2f"),
                    "titulo_limpio": st.column_config.TextColumn("Titular", width="large")
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No se encontraron noticias coincidentes con los filtros seleccionados.")
            
    with tab3:
        st.subheader("EvaluaciÃ³n Institucional y Autoridades (@Menciones)")
        st.write("AnÃ¡lisis de la percepciÃ³n dirigida hacia las principales entidades pÃºblicas encargadas de la infraestructura y movilidad en Twitter.")
        
        if df_entidades is not None and not df_entidades.empty:
            c_ent1, c_ent2 = st.columns([1, 1])
            
            with c_ent1:
                fig_ent = px.bar(
                    df_entidades,
                    x='Mencion_Entidad',
                    y=['Comentarios_Negativos', 'Comentarios_Neutros', 'Comentarios_Positivos'],
                    title="Sentimientos por Entidad / Funcionario",
                    labels={'value': 'Cantidad de Comentarios', 'variable': 'Sentimiento'},
                    color_discrete_map={
                        'Comentarios_Negativos': '#E53935',
                        'Comentarios_Neutros': '#FB8C00',
                        'Comentarios_Positivos': '#43A047'
                    },
                    barmode='stack'
                )
                st.plotly_chart(fig_ent, use_container_width=True)
                
            with c_ent2:
                fig_pct = px.bar(
                    df_entidades,
                    x='Mencion_Entidad',
                    y='%_Negativo',
                    title="% PercepciÃ³n Negativa por Entidad",
                    color='%_Negativo',
                    color_continuous_scale='Reds',
                    text='%_Negativo'
                )
                fig_pct.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
                st.plotly_chart(fig_pct, use_container_width=True)
                
            st.markdown("#### Tabla Detallada por Entidad")
            st.dataframe(df_entidades, use_container_width=True)
        else:
            st.info("No se encontrÃ³ el resumen consolidado de entidades.")
            
    with tab4:
        st.subheader("EvoluciÃ³n Temporal de Reportes (Twitter vs Google News)")
        
        # ComparaciÃ³n temporal
        df_time_tw = pd.DataFrame()
        df_time_news = pd.DataFrame()
        
        if 'fecha_dt' in df_filtrado.columns and not df_filtrado['fecha_dt'].isna().all():
            df_time_tw = df_filtrado.groupby(df_filtrado['fecha_dt'].dt.date).size().reset_index(name='Twitter (CiudadanÃ­a)')
            
        if not df_noticias_filtrado.empty and 'fecha_dt' in df_noticias_filtrado.columns and not df_noticias_filtrado['fecha_dt'].isna().all():
            df_time_news = df_noticias_filtrado.groupby(df_noticias_filtrado['fecha_dt'].dt.date).size().reset_index(name='Google News (Prensa)')
            
        if not df_time_tw.empty or not df_time_news.empty:
            df_merged_time = pd.merge(df_time_tw, df_time_news, on='fecha_dt', how='outer').fillna(0).sort_values('fecha_dt')
            
            fig_comp_time = px.line(
                df_merged_time,
                x='fecha_dt',
                y=[c for c in df_merged_time.columns if c != 'fecha_dt'],
                title="Volumen Temporal Comparativo: Comentarios en Twitter vs Cobertura de Prensa",
                labels={'fecha_dt': 'Fecha', 'value': 'Volumen de Publicaciones'},
                markers=True
            )
            st.plotly_chart(fig_comp_time, use_container_width=True)
        else:
            st.info("InformaciÃ³n de fechas no disponible en el subconjunto filtrado.")
            
    with tab5:
        st.subheader("Explorador Interactivo de Comentarios Ciudadanos (Twitter)")
        st.write(f"Mostrando **{len(df_filtrado)}** registros coincidentes.")
        
        # Columnas a mostrar
        cols_mostrar = ['autor_username', 'sentimiento_etiqueta', 'confianza_sentimiento', 'texto_limpio', 'menciones', 'fecha_publicacion', 'url']
        cols_existentes = [c for c in cols_mostrar if c in df_filtrado.columns]
        
        st.dataframe(
            df_filtrado[cols_existentes],
            column_config={
                "url": st.column_config.LinkColumn("Enlace Tweet"),
                "confianza_sentimiento": st.column_config.NumberColumn("Confianza", format="%.2f"),
                "texto_limpio": st.column_config.TextColumn("Texto del Comentario", width="large")
            },
            use_container_width=True,
            hide_index=True
        )

else:
    st.error("Error al cargar los conjuntos de datos. Verifique la ruta de los archivos CSV.")
