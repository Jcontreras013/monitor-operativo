import io
import pandas as pd
import streamlit as st
from functools import partial

from tools import read_file_robust, procesar_dataframe_base

# ==============================================================================
# AUDITORÍA DE MATERIALES: CEPHEUS vs. MOVIMIENTOS DE BODEGA (ODOO)
# ==============================================================================
# El problema que resuelve este módulo: la razón de cierre que el técnico
# elige en Cepheus (ej. "Corte de Acometida") no siempre refleja lo que
# realmente hizo -- a veces solo corrió reserva o no tenía material y aun así
# cierra con una razón que implica un cambio de cable. La única forma
# objetiva de confirmarlo es cruzar contra lo que de verdad salió de bodega
# (el reporte de movimientos de stock que exporta Odoo).

ACTIVIDADES_FIBRA_DEFAULT = ['SOPFIBRA', 'SOPFIBRACORP']
RAZONES_EXIGEN_METRAJE_DEFAULT = "CORTE DE ACOMETIDA"

# Nombres posibles de la columna de cantidad realmente entregada en el
# reporte stock.move.line de Odoo, en orden de preferencia. "Reservado" NO
# sirve: es lo apartado, no lo que salió.
COLUMNAS_METROS_ODOO = ['HECHO', 'CANTIDAD HECHA', 'CANTIDAD REALIZADA', 'QUANTITY DONE', 'DONE', 'CANTIDAD']
UNIDADES_METRO = {'m', 'mt', 'mts', 'metro', 'metros'}

SIN_ORDEN_CEPHEUS = 'N/D (orden no encontrada en Cepheus)'
ACTIVIDAD_SIN_ORDEN = 'SIN ORDEN EN CEPHEUS'

# Subirlo cada vez que cambie la forma del dict de resultados: así una
# sesión que cruzó con una versión anterior pide volver a cruzar en vez de
# mostrar datos incompletos o fallar por una llave que no existe.
VERSION_RESULTADO = 4


def _normalizar_num(serie):
    return serie.astype(str).str.replace(r'\.0$', '', regex=True).str.strip()


def _columnas_odoo(df_odoo):
    """Ubica las columnas del reporte stock.move.line de Odoo, o falla diciendo cuáles faltan."""
    cols_por_nombre = {str(c).strip().upper(): c for c in df_odoo.columns}
    columnas = {
        'producto': next((c for c in df_odoo.columns if 'PRODUCTO' in str(c).upper()), None),
        'unidad': next((c for c in df_odoo.columns if 'UNIDAD' in str(c).upper()), None),
        'origen': next((c for c in df_odoo.columns if 'ORIGEN' in str(c).upper()), None),
        'cantidad': next((cols_por_nombre[n] for n in COLUMNAS_METROS_ODOO if n in cols_por_nombre), None),
    }
    nombres = {'producto': 'Producto', 'unidad': 'Unidad de medida', 'origen': 'Origen', 'cantidad': 'Hecho (cantidad entregada)'}
    faltantes = [nombres[k] for k, v in columnas.items() if v is None]
    if faltantes:
        raise ValueError(
            "El archivo de Odoo no tiene las columnas esperadas: " + ", ".join(faltantes)
            + f". Columnas encontradas: {', '.join(map(str, df_odoo.columns))}"
        )
    columnas['fecha'] = cols_por_nombre.get('FECHA')
    return columnas


def extraer_fibra_odoo(df_odoo):
    """
    Deja solo los movimientos de fibra medidos en metros, con columnas
    normalizadas ORDEN_NORM / PRODUCTO / METROS. Conectores, patch cords,
    fajillas, etc. no sirven para confirmar si hubo un lanzamiento real.
    Devuelve (df_fibra, nombre_columna_metros_usada).
    """
    col = _columnas_odoo(df_odoo)
    es_fibra = df_odoo[col['producto']].astype(str).str.upper().str.contains('FIBRA', na=False)
    es_metro = df_odoo[col['unidad']].astype(str).str.strip().str.lower().isin(UNIDADES_METRO)
    mask = es_fibra & es_metro

    df_fibra = pd.DataFrame({
        'ORDEN_NORM': _normalizar_num(df_odoo.loc[mask, col['origen']]),
        'PRODUCTO': df_odoo.loc[mask, col['producto']].astype(str),
        'METROS': pd.to_numeric(df_odoo.loc[mask, col['cantidad']], errors='coerce').fillna(0),
    })
    return df_fibra, str(col['cantidad'])


# ------------------------------------------------------------------------------
# USO DE CAJAS MOLEX: lo depurado en Odoo contra lo que dice el comentario
# ------------------------------------------------------------------------------
# Odoo dice que se depuró una molex, no que se instaló. Criterio de MAXCOM:
#   - toda casa ya tiene su molex desde la instalación (INSFIBRA), y esa se
#     depuró en ese momento. Si en un cambio de acometida el técnico menciona
#     "la molex" de la casa ("fibra dañada en la molex, se preparó y se
#     fusiona"), NO se vuelve a depurar;
#   - la que sí se depura es una molex NUEVA EN MEDIO del tramo, entre la mufa
#     y la casa, para empalmar ("se le añadió una molex", "se le puso una
#     molex temporal", "molex en medio").
# Reglas sacadas de los cortes de acometida de septiembre 2026.
MOLEX_NUEVA = (
    r"MOLEX (EN MEDIO|A MITAD|INTERMEDIA|EN EL POSTE|EN EL TRAMO)|(EN MEDIO|A MITAD|MITAD DEL)[^.,]{0,30}MOLEX|"
    r"EMPALM[^.,]{0,20}MOLEX|"
    r"(DEJ[OAE]|DEJAR|PUS[OI]|PONER|COLOC|INSTAL|ANADI|AGREG|SE USO|UTILIZ|HACERLE|HACER UNA|"
    r"SE HIZO UNA|CAMBI[OA]R? (LA |DE )?(CAJA )?)[^.,]{0,25}MOLEX\b(?! NUEVAMENTE)|MOLEX (NUEVA\b|TEMPORAL|PROVISIONAL)"
)
# "Hasta una molex que ya estaba" o "se eliminó la molex" no dejan duda,
# aunque la misma frase diga "una molex": se revisan antes que lo nuevo.
MOLEX_EXISTENTE_SEGURO = r"MOLEX (QUE YA|YA EXISTENTE|EXISTENTE|DEL CLIENTE|INTERNA DEL)|(ELIMIN|RETIR|QUIT)[^.,]{0,25}MOLEX"
MOLEX_EXISTENTE = (
    r"(TENIA|TIENE|HABIA|ESTA|ENCONTRABA CON)( UNA| DOS)?( CAJA)? MOLEX|"
    r"(SU|LA|EN LA|DE LA|DENTRO DE LA)( CAJA)? MOLEX|MOLEX (DE LA CASA|INTERNA|DENTRO)|"
    r"(DANAD|DAAD|CORTAD|COMID|HILO)[^.,]{0,40}EN UNA( CAJA)? MOLEX|"
    r"MOLEX[^.,]{0,40}(PREPAR|REPAR|REPER|DANAR|DAAR)|PREPAR[^.,]{0,20}MOLEX|MOLEX NUEVAMENTE"
)
# Sin mencionar la molex: cambiar un tramo o dejar una reparación provisional
# obliga a empalmar, así que una molex es posible aunque no se nombre.
TRABAJO_CON_EMPALME = r"TRAMO|PROVISIONAL|TEMPORAL|EMPALM"

COMENTARIO_NUEVA = 'Molex nueva en medio del tramo'
COMENTARIO_EXISTENTE = 'Molex de la casa (ya depurada en la instalación)'
COMENTARIO_AMBIGUO = 'Menciona molex sin decir si es en medio o la de la casa'
COMENTARIO_REEMPLAZO_CASA = 'Molex nueva en la casa (reemplazo)'
COMENTARIO_EMPALME = 'Cambió un tramo / reparación provisional'
COMENTARIO_NADA = 'No menciona molex'

VEREDICTO_CUADRA = '✅ Cuadra'
VEREDICTO_PROBABLE = '🟡 Probable'
VEREDICTO_REVISAR = '🔎 Revisar'
VEREDICTO_CONTRADICE = '❌ Contradice'
VEREDICTO_SIN_RESPALDO = '⚠️ Sin respaldo'
VEREDICTO_SIN_DEPURAR = '🔍 Usada sin depurar'
# Orden de gravedad para ordenar la tabla (lo más grave primero).
ORDEN_VEREDICTOS = [VEREDICTO_CONTRADICE, VEREDICTO_SIN_RESPALDO, VEREDICTO_SIN_DEPURAR,
                    VEREDICTO_REVISAR, VEREDICTO_PROBABLE, VEREDICTO_CUADRA]
EXPLICACION_VEREDICTOS = {
    VEREDICTO_CONTRADICE: 'Depuró molex, pero el comentario habla de la molex de la casa, que ya se depuró en la instalación.',
    VEREDICTO_SIN_RESPALDO: 'Depuró molex y el comentario no menciona una molex en medio ni un empalme en el tramo.',
    VEREDICTO_SIN_DEPURAR: 'El comentario dice que puso una molex nueva (en medio del tramo o de reemplazo), pero no se depuró en Odoo.',
    VEREDICTO_REVISAR: ('Depuró molex y el comentario la menciona sin aclarar si fue en medio del tramo o la de la casa, '
                        'o dice que reemplazó la de la casa (solo vale si la anterior ya no estaba).'),
    VEREDICTO_PROBABLE: 'Depuró molex; no la menciona, pero cambió un tramo o dejó una reparación provisional (empalme en medio).',
    VEREDICTO_CUADRA: 'Lo depurado coincide con lo que dice el comentario.',
}


def _sin_acentos_mayus(texto):
    """
    Mayúsculas sin acentos, carácter por carácter (mismo largo que el original,
    para poder recortar la frase del texto original). Cepheus a veces entrega
    la ñ dañada como "¿" ("da¿aron"): se lee como N.
    """
    import unicodedata
    return ''.join((unicodedata.normalize('NFKD', ch)[:1] or ch) for ch in str(texto).replace('¿', 'n')).upper()


def clasificar_comentario_molex(comentario):
    """Devuelve (qué dice del uso de molex, frase del comentario que lo muestra)."""
    import re
    original = '' if pd.isna(comentario) else str(comentario)
    texto = _sin_acentos_mayus(original)

    def frase(inicio, fin):
        inicio, fin = max(0, inicio - 70), min(len(original), fin + 70)
        return ('…' if inicio else '') + original[inicio:fin].strip() + ('…' if fin < len(original) else '')

    if 'MOLEX' in texto:
        for patron, tipo in ((MOLEX_EXISTENTE_SEGURO, COMENTARIO_EXISTENTE), (MOLEX_NUEVA, COMENTARIO_NUEVA),
                             (MOLEX_EXISTENTE, COMENTARIO_EXISTENTE)):
            m = re.search(patron, texto)
            if m:
                # "Se dejó molex en la casa ya que no se encontró la que tenían":
                # es nueva, pero reemplaza la de la casa, no va en medio.
                if tipo == COMENTARIO_NUEVA and 'CASA' in texto[m.end():m.end() + 25]:
                    tipo = COMENTARIO_REEMPLAZO_CASA
                return tipo, frase(m.start(), m.end())
        i = texto.find('MOLEX')
        return COMENTARIO_AMBIGUO, frase(i, i + 5)
    m = re.search(TRABAJO_CON_EMPALME, texto)
    if m:
        return COMENTARIO_EMPALME, frase(m.start(), m.end())
    return COMENTARIO_NADA, frase(0, 150) if original else ''


def veredicto_molex(cajas_depuradas, lo_que_dice):
    """Veredicto de una orden según si se depuró molex y qué dice el comentario (None = no aplica)."""
    if cajas_depuradas > 0:
        return {
            COMENTARIO_NUEVA: VEREDICTO_CUADRA,
            COMENTARIO_EMPALME: VEREDICTO_PROBABLE,
            COMENTARIO_AMBIGUO: VEREDICTO_REVISAR,
            COMENTARIO_REEMPLAZO_CASA: VEREDICTO_REVISAR,
            COMENTARIO_EXISTENTE: VEREDICTO_CONTRADICE,
        }.get(lo_que_dice, VEREDICTO_SIN_RESPALDO)
    # Sin depuración, mencionar la molex sin aclarar casi siempre es la de la
    # casa, que no se depura: cuadra. Solo falta la depuración si dice en medio.
    return {
        COMENTARIO_NUEVA: VEREDICTO_SIN_DEPURAR,
        COMENTARIO_REEMPLAZO_CASA: VEREDICTO_SIN_DEPURAR,
        COMENTARIO_AMBIGUO: VEREDICTO_CUADRA,
        COMENTARIO_EXISTENTE: VEREDICTO_CUADRA,
    }.get(lo_que_dice)


def analizar_uso_molex(df_cep, df_odoo, actividades, razones):
    """
    Una sola tabla de uso de molex en las órdenes CERRADAS de `actividades`
    con razón de cierre en `razones` (por defecto SOPFIBRA/SOPFIBRACORP en
    Corte de acometida): las que tienen molex depurada en Odoo o la mencionan
    en el comentario de cierre, cada una con su veredicto.
    Devuelve (df_uso, resumen_por_tecnico).
    """
    col = _columnas_odoo(df_odoo)
    es_molex = df_odoo[col['producto']].astype(str).str.upper().str.contains('MOLEX', na=False)
    cajas = pd.to_numeric(df_odoo.loc[es_molex, col['cantidad']], errors='coerce').fillna(0) \
        .groupby(_normalizar_num(df_odoo.loc[es_molex, col['origen']])).sum()

    act = df_cep['ACTIVIDAD'].astype(str).str.upper().str.strip()
    est = df_cep['ESTADO'].astype(str).str.upper().str.strip()
    razon = df_cep['RAZON_CIERRE_SOP'].astype(str).str.upper().str.strip() if 'RAZON_CIERRE_SOP' in df_cep.columns \
        else pd.Series('', index=df_cep.index)
    df = df_cep[act.isin([a.upper().strip() for a in actividades]) & (est == 'CERRADA')
                & razon.isin([r.upper().strip() for r in razones])].drop_duplicates('NUM_NORM').copy()

    columnas = ['ORDEN', 'TECNICO', 'ACTIVIDAD', 'CLIENTE', 'FECHA_CIERRE', 'MOLEX_DEPURADAS',
                'QUE_DICE_EL_COMENTARIO', 'VEREDICTO', 'FRASE_DEL_COMENTARIO', 'COMENTARIO']
    columnas_resumen = ['TECNICO', 'ORDENES_EVALUADAS', 'MOLEX_DEPURADAS'] + ORDEN_VEREDICTOS
    if df.empty:
        return pd.DataFrame(columns=columnas), pd.DataFrame(columns=columnas_resumen)

    df['MOLEX_DEPURADAS'] = df['NUM_NORM'].map(cajas).fillna(0).astype(int)
    comentario = df['COMENTARIO_CIERRE'] if 'COMENTARIO_CIERRE' in df.columns else pd.Series('', index=df.index)
    clasif = comentario.apply(clasificar_comentario_molex)
    df['QUE_DICE_EL_COMENTARIO'] = clasif.str[0]
    df['FRASE_DEL_COMENTARIO'] = clasif.str[1]
    df['VEREDICTO'] = [veredicto_molex(c, q) for c, q in zip(df['MOLEX_DEPURADAS'], df['QUE_DICE_EL_COMENTARIO'])]
    df['COMENTARIO'] = comentario
    # El rep_actividades trae dd/mm/aaaa y Sheets aaaa-mm-dd: sin dayfirst
    # el 03/09 se leía como 9 de marzo y el 15/09 quedaba vacío.
    df['FECHA_CIERRE'] = pd.to_datetime(df['HORA_LIQ'].astype(str), format='mixed', dayfirst=True, errors='coerce') \
        .dt.strftime('%d/%m/%Y %H:%M') if 'HORA_LIQ' in df.columns else ''

    resumen = df.groupby('TECNICO').agg(ORDENES_EVALUADAS=('NUM_NORM', 'count'),
                                        MOLEX_DEPURADAS=('MOLEX_DEPURADAS', 'sum')).reset_index()
    conteo = pd.crosstab(df['TECNICO'], df['VEREDICTO']).reindex(columns=ORDEN_VEREDICTOS, fill_value=0)
    resumen = resumen.merge(conteo, left_on='TECNICO', right_index=True, how='left').fillna(0)
    resumen[ORDEN_VEREDICTOS] = resumen[ORDEN_VEREDICTOS].astype(int)
    resumen = resumen[columnas_resumen].sort_values(
        [VEREDICTO_CONTRADICE, VEREDICTO_SIN_RESPALDO, 'MOLEX_DEPURADAS'], ascending=False).reset_index(drop=True)

    df_uso = df[df['VEREDICTO'].notna()].rename(columns={'NUM_NORM': 'ORDEN'})
    df_uso = df_uso.assign(_g=df_uso['VEREDICTO'].map({v: i for i, v in enumerate(ORDEN_VEREDICTOS)})) \
        .sort_values(['_g', 'TECNICO', 'ORDEN'])
    return df_uso[[c for c in columnas if c in df_uso.columns]].reset_index(drop=True), resumen


def cruzar_cepheus_odoo(df_cep, metraje_por_orden, actividades, razones_exigen_metraje):
    """
    Regla aplicada: entre las órdenes CERRADAS de las actividades indicadas,
    las que se cerraron con una razón de la lista `razones_exigen_metraje`
    deben tener metraje de fibra en Odoo. Las que no lo tienen quedan
    marcadas como SIN_METRAJE; si además el comentario de cierre menciona
    "reserva", se marca MENCIONA_RESERVA -- es la prueba más clara de que el
    propio técnico admite que no hizo el cambio.
    Devuelve (df_detalle, df_resumen_por_tecnico).
    """
    act_upper = df_cep['ACTIVIDAD'].astype(str).str.upper().str.strip()
    est_upper = df_cep['ESTADO'].astype(str).str.upper().str.strip()
    actividades_upper = [a.upper().strip() for a in actividades]
    df_sel = df_cep[act_upper.isin(actividades_upper) & (est_upper == 'CERRADA')].copy()

    df_sel = df_sel.merge(metraje_por_orden, left_on='NUM_NORM', right_index=True, how='left')
    df_sel['METRAJE_ODOO'] = df_sel['METRAJE_ODOO'].fillna(0)

    razones_upper = [r.upper().strip() for r in razones_exigen_metraje]
    razon_orden_upper = df_sel['RAZON_CIERRE_SOP'].astype(str).str.upper().str.strip()
    df_sel = df_sel[razon_orden_upper.isin(razones_upper)].copy()

    df_sel['SIN_METRAJE'] = df_sel['METRAJE_ODOO'] <= 0
    com_upper = df_sel['COMENTARIO_CIERRE'].astype(str).str.upper()
    df_sel['MENCIONA_RESERVA'] = df_sel['SIN_METRAJE'] & com_upper.str.contains('RESERVA', na=False)

    columnas_detalle = [
        'NUM_NORM', 'TECNICO', 'ACTIVIDAD', 'RAZON_CIERRE_SOP', 'COMENTARIO_CIERRE',
        'CLIENTE', 'HORA_LIQ', 'METRAJE_ODOO', 'SIN_METRAJE', 'MENCIONA_RESERVA',
    ]
    df_detalle = df_sel[[c for c in columnas_detalle if c in df_sel.columns]].rename(columns={
        'NUM_NORM': 'ORDEN',
        'RAZON_CIERRE_SOP': 'RAZON_CIERRE',
        'COMENTARIO_CIERRE': 'COMENTARIO',
        'HORA_LIQ': 'FECHA_CIERRE',
    })

    resumen = df_sel.groupby('TECNICO').agg(
        TOTAL_ORDENES=('NUM_NORM', 'count'),
        SIN_METRAJE=('SIN_METRAJE', 'sum'),
        MENCIONAN_RESERVA=('MENCIONA_RESERVA', 'sum'),
        METROS_ODOO=('METRAJE_ODOO', 'sum'),
    ).reset_index()
    resumen['CON_METRAJE'] = resumen['TOTAL_ORDENES'] - resumen['SIN_METRAJE']
    resumen['PCT_SIN_METRAJE'] = (resumen['SIN_METRAJE'] / resumen['TOTAL_ORDENES'] * 100).round(1)
    resumen = resumen[[
        'TECNICO', 'TOTAL_ORDENES', 'CON_METRAJE', 'SIN_METRAJE', 'PCT_SIN_METRAJE',
        'MENCIONAN_RESERVA', 'METROS_ODOO',
    ]].sort_values('SIN_METRAJE', ascending=False).reset_index(drop=True)

    return df_detalle, resumen


def _agrupar_metros(df_ordenes, columnas):
    grupo = df_ordenes.groupby(columnas).agg(
        ORDENES=('ORDEN_NORM', 'nunique'),
        METROS=('METROS', 'sum'),
    ).reset_index()
    grupo['PROMEDIO_M_X_ORDEN'] = (grupo['METROS'] / grupo['ORDENES']).round(1)
    return grupo


def calcular_metraje_real_usado(df_cep, df_fibra):
    """
    Metraje REAL de fibra retirado de bodega en todo el periodo del archivo
    de Odoo, sin filtrar por razón de cierre. Técnico y actividad se toman
    de Cepheus cruzando por número de orden (más confiable que parsear el
    nombre desde el campo "Desde" de Odoo); lo que no aparece en Cepheus
    queda en una fila aparte para que se note, no se pierde.

    El desglose por técnico va SIEMPRE separado por actividad: un PEXTERNO
    o una INSFIBRA consumen mucho más cable que un SOPFIBRA, así que
    sumarlos juntos hace que el promedio por técnico no sea comparable.
    Devuelve (df_por_orden, por_producto, por_actividad, por_tecnico).
    """
    por_producto = df_fibra.groupby('PRODUCTO').agg(
        MOVIMIENTOS=('METROS', 'count'),
        METROS=('METROS', 'sum'),
    ).reset_index().sort_values('METROS', ascending=False).reset_index(drop=True)

    df_por_orden = df_fibra.groupby('ORDEN_NORM')['METROS'].sum().reset_index()
    datos_orden = df_cep.drop_duplicates('NUM_NORM').set_index('NUM_NORM')
    df_por_orden['TECNICO'] = df_por_orden['ORDEN_NORM'].map(datos_orden['TECNICO']).fillna(SIN_ORDEN_CEPHEUS)
    df_por_orden['ACTIVIDAD'] = (
        df_por_orden['ORDEN_NORM'].map(datos_orden['ACTIVIDAD'])
        .astype(str).str.upper().str.strip()
        .where(df_por_orden['ORDEN_NORM'].isin(datos_orden.index), ACTIVIDAD_SIN_ORDEN)
    )

    por_actividad = _agrupar_metros(df_por_orden, ['ACTIVIDAD']) \
        .sort_values('METROS', ascending=False).reset_index(drop=True)
    por_tecnico = _agrupar_metros(df_por_orden, ['ACTIVIDAD', 'TECNICO'])
    orden_actividad = {a: i for i, a in enumerate(por_actividad['ACTIVIDAD'])}
    por_tecnico = por_tecnico.assign(_o=por_tecnico['ACTIVIDAD'].map(orden_actividad)) \
        .sort_values(['_o', 'METROS'], ascending=[True, False]) \
        .drop(columns='_o').reset_index(drop=True)

    return df_por_orden, por_producto, por_actividad, por_tecnico


def procesar_auditoria_materiales(df_cepheus_crudo, df_odoo_crudo, actividades, razones):
    """Corre todo el análisis y devuelve un solo dict con los resultados."""
    df_cep = procesar_dataframe_base(df_cepheus_crudo.copy())
    df_cep['NUM_NORM'] = _normalizar_num(df_cep['NUM'])

    df_fibra, col_metros = extraer_fibra_odoo(df_odoo_crudo)
    metraje_por_orden = df_fibra.groupby('ORDEN_NORM')['METROS'].sum().rename('METRAJE_ODOO')

    df_detalle, resumen = cruzar_cepheus_odoo(df_cep, metraje_por_orden, actividades, razones)
    df_por_orden, por_producto, por_actividad, por_tecnico = calcular_metraje_real_usado(df_cep, df_fibra)

    df_uso_molex, resumen_molex = analizar_uso_molex(df_cep, df_odoo_crudo, actividades, razones)

    total_metros = float(df_fibra['METROS'].sum())
    en_cepheus = df_por_orden['ACTIVIDAD'] != ACTIVIDAD_SIN_ORDEN
    en_actividades = df_por_orden['ACTIVIDAD'].isin([a.upper().strip() for a in actividades])

    return {
        'version': VERSION_RESULTADO,
        'molex': df_uso_molex,
        'molex_por_tecnico': resumen_molex,
        'detalle': df_detalle,
        'resumen': resumen,
        'metraje_por_producto': por_producto,
        'metraje_por_actividad': por_actividad,
        'metraje_por_tecnico': por_tecnico,
        'total_metros': total_metros,
        'metros_con_orden_cepheus': float(df_por_orden.loc[en_cepheus, 'METROS'].sum()),
        'metros_sin_orden_cepheus': float(df_por_orden.loc[~en_cepheus, 'METROS'].sum()),
        'metros_actividades_evaluadas': float(df_por_orden.loc[en_actividades, 'METROS'].sum()),
        'metros_ordenes_evaluadas': float(df_detalle['METRAJE_ODOO'].sum()),
        'col_metros': col_metros,
        'actividades': list(actividades),
        'razones': [r.strip().upper() for r in razones],
    }


# ==============================================================================
# ALERTA POR CORREO: MOLEX EN COMENTARIOS DE CIERRE (la envía sync_job.py)
# ==============================================================================
# Se revisa en cada ciclo del robot (cada 15 min) con los datos de Cepheus,
# sin esperar al archivo de Odoo: si el técnico menciona una molex en el
# comentario de cierre de un soporte, se avisa para revisar si la usó.
ACTIVIDADES_ALERTA_MOLEX = ('SOPFIBRA', 'SOPFIBRACORP')


def seleccionar_molex_en_comentarios(df_ordenes, ya_avisadas, ahora, horas=24):
    """
    Soportes CERRADOS en las últimas `horas` cuyo comentario de cierre dice
    que se puso una molex nueva en medio del tramo y que no se hayan avisado. La ventana evita que, al
    activar la alerta, lleguen de golpe todos los cierres viejos que siguen
    en la consulta de 55 días del robot.
    """
    columnas = ('NUM', 'ACTIVIDAD', 'ESTADO', 'HORA_LIQ', 'COMENTARIO_CIERRE')
    if df_ordenes is None or df_ordenes.empty or any(c not in df_ordenes.columns for c in columnas):
        return pd.DataFrame()
    df = df_ordenes.copy()
    df['NUM'] = _normalizar_num(df['NUM'])
    es_soporte = df['ACTIVIDAD'].astype(str).str.upper().str.strip().isin(ACTIVIDADES_ALERTA_MOLEX)
    cerrada = df['ESTADO'].astype(str).str.upper().str.strip() == 'CERRADA'
    menciona = df['COMENTARIO_CIERRE'].astype(str).str.upper().str.contains('MOLEX', na=False)
    reciente = pd.to_datetime(df['HORA_LIQ'], errors='coerce') >= pd.Timestamp(ahora) - pd.Timedelta(hours=horas)
    nuevas = df[es_soporte & cerrada & menciona & reciente & ~df['NUM'].isin(set(ya_avisadas)) & (df['NUM'] != 'N/D')]
    nuevas = nuevas.drop_duplicates('NUM').copy()
    if nuevas.empty:
        return nuevas
    # Solo se avisa cuando el técnico dice que puso una molex NUEVA EN MEDIO del
    # tramo: esa es la que debe tener una depuración en Odoo. La molex de la
    # casa ("se preparó la molex", "fibra dañada en la molex") ya se depuró en
    # la instalación y no genera aviso.
    clasif = nuevas['COMENTARIO_CIERRE'].apply(clasificar_comentario_molex)
    nuevas['QUE_DICE_EL_COMENTARIO'] = clasif.str[0]
    nuevas['FRASE_DEL_COMENTARIO'] = clasif.str[1]
    return nuevas[nuevas['QUE_DICE_EL_COMENTARIO'].isin([COMENTARIO_NUEVA, COMENTARIO_REEMPLAZO_CASA])]


def armar_correo_molex(df_nuevas):
    """Devuelve (asunto, texto, html) de la alerta de molex en comentarios de cierre."""
    from notificaciones import tabla_html

    columnas = {
        'NUM': 'Orden', 'TECNICO': 'Técnico', 'ACTIVIDAD': 'Actividad', 'CLIENTE': 'Cliente',
        'HORA_LIQ': 'Cierre', 'RAZON_CIERRE_SOP': 'Razón de cierre', 'QUE_DICE_EL_COMENTARIO': 'Qué dice',
        'FRASE_DEL_COMENTARIO': 'Comentario de cierre',
    }
    tabla = df_nuevas[[c for c in columnas if c in df_nuevas.columns]].rename(columns=columnas)
    if 'Cierre' in tabla.columns:
        tabla['Cierre'] = pd.to_datetime(tabla['Cierre'], errors='coerce').dt.strftime('%d/%m/%Y %H:%M')
    asunto = f"⚠️ Molex en cierre de soporte: {len(df_nuevas)} orden(es) por revisar"
    intro = (
        f"En {len(df_nuevas)} orden(es) de soporte ({', '.join(sorted(df_nuevas['ACTIVIDAD'].astype(str).unique()))}) "
        "el técnico dice en el comentario de cierre que puso una caja molex nueva en medio del tramo. "
        "Revisar que esté depurada en Odoo (la molex de la casa ya se depuró en la instalación)."
    )
    texto = intro + "\n\n" + "\n".join(
        " | ".join(f"{k}: {v}" for k, v in fila.items()) for fila in tabla.fillna('').to_dict('records')
    ) + "\n\nMonitor Operativo MAXCOM - alerta automática"
    cuerpo_html = (
        f'<div style="font-family:Arial,sans-serif;font-size:13px;"><p>{intro}</p>'
        f"{tabla_html(tabla)}"
        '<p style="color:#666;font-size:11px;">Monitor Operativo MAXCOM · alerta automática cada 15 min. '
        "Cada orden se avisa una sola vez.</p></div>"
    )
    return asunto, texto, cuerpo_html


# ==============================================================================
# INTERFAZ STREAMLIT
# ==============================================================================
COLUMNAS_PANTALLA_MOLEX = ['ORDEN', 'TECNICO', 'ACTIVIDAD', 'CLIENTE', 'FECHA_CIERRE', 'MOLEX_DEPURADAS',
                           'QUE_DICE_EL_COMENTARIO', 'VEREDICTO']


def armar_correo_uso_molex(df_uso, razones):
    """(asunto, texto, html) con las órdenes cuyo uso de molex no cuadra, con la frase del comentario."""
    from notificaciones import tabla_html

    df = df_uso[df_uso['VEREDICTO'] != VEREDICTO_CUADRA]
    columnas = {'ORDEN': 'Orden', 'TECNICO': 'Técnico', 'FECHA_CIERRE': 'Cierre', 'MOLEX_DEPURADAS': 'Molex depuradas',
                'VEREDICTO': 'Veredicto', 'FRASE_DEL_COMENTARIO': 'Lo que dice el comentario'}
    tabla = df[list(columnas)].rename(columns=columnas)
    conteo = ', '.join(f"{v}: {n}" for v, n in df['VEREDICTO'].value_counts().reindex(ORDEN_VEREDICTOS).dropna().astype(int).items())
    asunto = f"📦 Uso de molex: {len(df)} orden(es) por revisar ({', '.join(razones).title()})"
    intro = (f"Órdenes cerradas como {', '.join(razones).title()} en las que lo depurado en Odoo no coincide con lo "
             f"que el técnico escribió al cerrar. {conteo}.")
    leyenda = ''.join(f"<li><b>{v}</b>: {EXPLICACION_VEREDICTOS[v]}</li>" for v in ORDEN_VEREDICTOS if v != VEREDICTO_CUADRA)
    texto = intro + "\n\n" + "\n".join(
        " | ".join(f"{k}: {v}" for k, v in fila.items()) for fila in tabla.fillna('').to_dict('records')
    ) + "\n\nMonitor Operativo MAXCOM - Auditoría de Materiales"
    cuerpo_html = (f'<div style="font-family:Arial,sans-serif;font-size:13px;"><p>{intro}</p>{tabla_html(tabla)}'
                   f'<ul style="font-size:12px;color:#444;">{leyenda}</ul>'
                   '<p style="color:#666;font-size:11px;">Monitor Operativo MAXCOM · Auditoría de Materiales.</p></div>')
    return asunto, texto, cuerpo_html


def mostrar_uso_molex(res):
    """Una sola tabla: lo depurado en Odoo contra lo que dice el comentario de cierre."""
    df_uso = res['molex']
    resumen = res['molex_por_tecnico']
    st.markdown(f"#### 📦 Uso de cajas molex · {' / '.join(res['actividades'])} cerradas como {', '.join(res['razones']).title()}")
    st.caption(
        "Odoo dice si se depuró una molex; el comentario de cierre dice si el técnico puso una nueva o trabajó en la "
        "que ya tenía el cliente. Aquí se ven los veredictos; la frase del comentario que explica cada uno va en el "
        "Excel, el PDF y el correo."
    )
    with st.expander("¿Qué significa cada veredicto?"):
        for v in ORDEN_VEREDICTOS:
            st.markdown(f"**{v}** — {EXPLICACION_VEREDICTOS[v]}")

    if df_uso.empty:
        st.success("✅ Ninguna orden evaluada tiene molex depurada ni la menciona en el comentario de cierre.")
        return

    conteo = df_uso['VEREDICTO'].value_counts()
    k = st.columns(len(ORDEN_VEREDICTOS))
    for col, v in zip(k, ORDEN_VEREDICTOS):
        col.metric(v, int(conteo.get(v, 0)))

    st.markdown("**Por técnico**")
    st.dataframe(resumen, use_container_width=True, hide_index=True)

    ocultar = st.checkbox("Ocultar las que cuadran", value=False, key="mat_molex_ocultar_cuadra")
    df_ver = df_uso[df_uso['VEREDICTO'] != VEREDICTO_CUADRA] if ocultar else df_uso
    st.dataframe(df_ver[COLUMNAS_PANTALLA_MOLEX], use_container_width=True, hide_index=True)

    por_revisar = int((df_uso['VEREDICTO'] != VEREDICTO_CUADRA).sum())
    if por_revisar and st.button(f"📧 Enviar por correo las {por_revisar} orden(es) por revisar", key="btn_mat_molex_correo"):
        from notificaciones import config_correo_streamlit, enviar_correo, lista_destinatarios
        config = config_correo_streamlit()
        with st.spinner("Enviando..."):
            ok, nota = enviar_correo(config, *armar_correo_uso_molex(df_uso, res['razones']))
        if ok:
            st.success(f"✅ Enviado a {len(lista_destinatarios(config))} destinatario(s).")
            if nota:
                st.warning(f"⚠️ Nota: {nota}.")
        else:
            st.error(f"❌ No se pudo enviar: {nota}")


# ------------------------------------------------------------------------------
# PRUEBA PILOTO DE IA (ia.py): la IA lee los comentarios de cierre y se compara
# contra las reglas actuales y contra el metraje real de Odoo.
# ------------------------------------------------------------------------------
_REGLAS_A_IA_MOLEX = {
    COMENTARIO_NUEVA: "Molex nueva en medio del tramo",
    COMENTARIO_REEMPLAZO_CASA: "Molex nueva en la casa (reemplazo)",
    COMENTARIO_EXISTENTE: "Molex de la casa (ya depurada en la instalación)",
    COMENTARIO_AMBIGUO: "Menciona molex sin decir dónde",
    COMENTARIO_EMPALME: "No menciona molex",
    COMENTARIO_NADA: "No menciona molex",
}
_IA_A_COMENTARIO = {
    "Molex nueva en medio del tramo": COMENTARIO_NUEVA,
    "Molex nueva en la casa (reemplazo)": COMENTARIO_REEMPLAZO_CASA,
    "Molex de la casa (ya depurada en la instalación)": COMENTARIO_EXISTENTE,
    "Menciona molex sin decir dónde": COMENTARIO_AMBIGUO,
    "No menciona molex": COMENTARIO_NADA,
}
COSTO_ESTIMADO_POR_ORDEN_USD = 0.015


def _clave_api_ia():
    try:
        return str(st.secrets["anthropic"]["api_key"]).strip()
    except Exception:
        return ""


def _ordenes_para_piloto(res):
    """Órdenes evaluadas (razón de cierre elegida), primero las que tocan molex y las sin metraje."""
    df = res['detalle'].copy()
    if df.empty:
        return df
    molex = res['molex']
    cajas = dict(zip(molex['ORDEN'], molex['MOLEX_DEPURADAS'])) if not molex.empty else {}
    df['MOLEX_DEPURADAS'] = df['ORDEN'].map(cajas).fillna(0).astype(int)
    df['_p'] = (~df['ORDEN'].isin(set(cajas))).astype(int) * 2 + (~df['SIN_METRAJE']).astype(int)
    return df.sort_values(['_p', 'ORDEN']).drop(columns='_p').reset_index(drop=True)


def comparar_piloto(df_ordenes, df_ia):
    """Une las órdenes con lo que dijo la IA y marca dónde no cuadra con las reglas u Odoo."""
    df = df_ordenes.merge(df_ia, on='ORDEN', how='inner')
    reglas = df['COMENTARIO'].apply(clasificar_comentario_molex).str[0]
    df['REGLAS_MOLEX'] = reglas.map(_REGLAS_A_IA_MOLEX)
    df['COINCIDE_MOLEX'] = df['REGLAS_MOLEX'] == df['IA_MOLEX']
    df['VEREDICTO_REGLAS'] = [veredicto_molex(c, q) or '' for c, q in zip(df['MOLEX_DEPURADAS'], reglas)]
    df['VEREDICTO_IA'] = [veredicto_molex(c, _IA_A_COMENTARIO.get(q)) or '' if q else ''
                          for c, q in zip(df['MOLEX_DEPURADAS'], df['IA_MOLEX'])]

    cambio = df['IA_TRABAJO_FIBRA'].isin(["Cambio completo de acometida", "Cambio de un tramo / reparación con empalme"])
    sin_cambio = df['IA_TRABAJO_FIBRA'].isin(["Solo corrió reserva (sin fibra nueva)", "Sin fibra nueva (conector, ONU, niveles...)"])
    odoo = pd.to_numeric(df['METRAJE_ODOO'], errors='coerce').fillna(0)
    ia_m = pd.to_numeric(df['IA_METROS_DECLARADOS'], errors='coerce')
    hallazgos = []
    for i in df.index:
        h = []
        if df.at[i, 'IA_RAZON_COINCIDE'] is False:
            h.append("La razón de cierre no cuadra con lo que dice el comentario")
        if cambio[i] and odoo[i] <= 0:
            h.append("Dice que cambió fibra, pero Odoo no tiene metraje")
        if sin_cambio[i] and odoo[i] > 0:
            h.append(f"Odoo tiene {odoo[i]:.0f} m de fibra, pero el comentario no describe fibra nueva")
        if pd.notna(ia_m[i]) and odoo[i] > 0 and abs(ia_m[i] - odoo[i]) > max(20, 0.2 * odoo[i]):
            h.append(f"Declara {ia_m[i]:.0f} m y Odoo tiene {odoo[i]:.0f} m")
        if df.at[i, 'VEREDICTO_IA'] not in ('', VEREDICTO_CUADRA):
            h.append(f"Molex: {df.at[i, 'VEREDICTO_IA']}")
        hallazgos.append(" · ".join(h))
    df['HALLAZGOS_IA'] = hallazgos
    return df


def mostrar_piloto_ia(res):
    with st.expander("🧪 Prueba piloto: la IA lee los comentarios de cierre", expanded=False):
        st.caption(
            "Claude (Anthropic) lee el comentario de cierre de cada orden evaluada y dice qué pasó con la molex, qué "
            "trabajo de fibra hubo y cuántos metros declara el técnico. Se compara contra las reglas actuales y contra "
            "el metraje real de Odoo. Solo se envía la actividad, la razón de cierre y el comentario (ningún dato del cliente)."
        )
        clave = _clave_api_ia()
        if not clave:
            st.info(
                "Para activar la prueba, agrega en Streamlit → Settings → Secrets (no en el chat ni en el código):\n\n"
                "```toml\n[anthropic]\napi_key = \"sk-ant-...\"\n```\n"
                "La clave se crea en console.anthropic.com → API Keys. Pon un límite de gasto mensual en Billing."
            )
            return
        df_ord = _ordenes_para_piloto(res)
        if df_ord.empty:
            st.info("No hay órdenes evaluadas para probar.")
            return

        c1, c2 = st.columns(2)
        cuantas = c1.number_input(f"Órdenes a analizar (de {len(df_ord)})", min_value=1, max_value=len(df_ord),
                                  value=min(30, len(df_ord)), step=10, key="ia_piloto_n",
                                  help="Primero van las que tocan molex y las que no tienen metraje en Odoo.")
        esfuerzo = c2.selectbox("Nivel de razonamiento", ["low", "medium"], key="ia_piloto_effort",
                                format_func={"low": "Bajo (más barato, suele bastar)", "medium": "Medio"}.get)
        st.caption(f"Costo estimado: ~${cuantas * COSTO_ESTIMADO_POR_ORDEN_USD:.2f} USD. El costo real se muestra al terminar.")

        clave_resultado = (len(df_ord), int(cuantas), esfuerzo, tuple(df_ord['ORDEN'].head(int(cuantas))))
        if st.button(f"🤖 Analizar {int(cuantas)} órdenes con IA", key="btn_ia_piloto", type="primary"):
            import ia
            barra = st.progress(0.0, text="Analizando...")
            try:
                df_ia, resumen = ia.ejecutar_piloto(
                    df_ord.head(int(cuantas))[['ORDEN', 'ACTIVIDAD', 'RAZON_CIERRE', 'COMENTARIO']],
                    clave, effort=esfuerzo,
                    al_avanzar=lambda n, t: barra.progress(n / t, text=f"Analizando {n} de {t}..."),
                )
                st.session_state['mat_piloto_ia'] = (clave_resultado, comparar_piloto(df_ord, df_ia), resumen)
            except Exception as e:
                tipo = type(e).__name__
                if tipo == "AuthenticationError":
                    st.error("❌ La clave de Anthropic no es válida. Revisa [anthropic] api_key en los secretos.")
                elif tipo == "PermissionDeniedError":
                    st.error("❌ La clave no tiene permiso para usar el modelo. Revisa la cuenta en console.anthropic.com.")
                else:
                    st.error(f"❌ No se pudo completar la prueba: {e}")
            finally:
                barra.empty()

        guardado = st.session_state.get('mat_piloto_ia')
        if not guardado or guardado[0] != clave_resultado:
            return
        _, df, resumen = guardado

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Órdenes analizadas", resumen['ordenes'] - resumen['errores'])
        k2.metric("Costo real", f"${resumen['costo_usd']:.3f}")
        k3.metric("Costo por orden", f"${resumen['costo_usd'] / max(resumen['ordenes'], 1):.4f}")
        k4.metric("Tiempo", f"{resumen['segundos']:.0f} s")
        if resumen['errores']:
            st.warning(f"⚠️ {resumen['errores']} orden(es) no se pudieron analizar (ver columna IA_ERROR en el Excel).")
        uso = resumen['uso']
        st.caption(f"Tokens: entrada {uso['entrada']:,} · salida {uso['salida']:,} · caché escrita "
                   f"{uso['cache_escritura']:,} · caché leída {uso['cache_lectura']:,} · modelo {resumen['modelo']}, "
                   f"razonamiento {resumen['effort']}. Al mes, con ~150 cierres diarios: "
                   f"~${resumen['costo_usd'] / max(resumen['ordenes'], 1) * 150 * 30:.0f} USD.")

        ok = df[df['IA_ERROR'] == '']
        st.markdown("**IA contra reglas actuales (molex)**")
        st.caption(f"Coinciden en {int(ok['COINCIDE_MOLEX'].sum())} de {len(ok)} órdenes. Donde no coinciden, "
                   "revisar el comentario dice cuál de las dos acertó.")
        st.dataframe(pd.crosstab(ok['REGLAS_MOLEX'], ok['IA_MOLEX']), use_container_width=True)

        con_hallazgo = df[df['HALLAZGOS_IA'] != '']
        st.markdown(f"**Órdenes donde la IA encontró algo para revisar: {len(con_hallazgo)}**")
        st.dataframe(con_hallazgo[['ORDEN', 'TECNICO', 'MOLEX_DEPURADAS', 'METRAJE_ODOO', 'IA_TRABAJO_FIBRA',
                                   'IA_METROS_DECLARADOS', 'IA_MOLEX', 'HALLAZGOS_IA']],
                     use_container_width=True, hide_index=True)

        buffer = io.BytesIO()
        columnas = ['ORDEN', 'TECNICO', 'ACTIVIDAD', 'RAZON_CIERRE', 'FECHA_CIERRE', 'METRAJE_ODOO', 'MOLEX_DEPURADAS',
                    'IA_TRABAJO_FIBRA', 'IA_METROS_DECLARADOS', 'IA_RAZON_COINCIDE', 'IA_MOLEX', 'REGLAS_MOLEX',
                    'COINCIDE_MOLEX', 'VEREDICTO_IA', 'VEREDICTO_REGLAS', 'HALLAZGOS_IA', 'IA_EVIDENCIA',
                    'IA_OBSERVACION', 'COMENTARIO', 'IA_ERROR', 'IA_COSTO_USD']
        hoja = df[[c for c in columnas if c in df.columns]].assign(REVISION_MANUAL_IA_ACERTO="")
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            hoja.to_excel(writer, sheet_name='Piloto IA', index=False)
            pd.DataFrame([{**{k: v for k, v in resumen.items() if k != 'uso'}, **resumen['uso']}]) \
                .to_excel(writer, sheet_name='Resumen', index=False)
        st.download_button("⬇️ Descargar resultado del piloto (Excel)", data=buffer.getvalue(),
                           file_name="piloto_ia_comentarios.xlsx", key="dl_piloto_ia", on_click="ignore",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.caption("En el Excel, la columna REVISION_MANUAL_IA_ACERTO es para marcar si la IA acertó en las "
                   "órdenes donde no coincide con las reglas: con eso medimos su precisión real.")


# ==============================================================================
# PANTALLA PRINCIPAL
# ==============================================================================
def mostrar_auditoria_materiales(*args, **kwargs):
    st.title("🔍 Auditoría de Materiales SOPFIBRA")
    st.caption(
        "Cruza las órdenes de Cepheus contra los materiales realmente retirados de bodega "
        "(reporte de movimientos de stock de Odoo), para detectar cierres que no tienen un "
        "lanzamiento de fibra real detrás."
    )
    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        archivo_cepheus = st.file_uploader(
            "1. rep_actividades (Cepheus)", type=['xlsx', 'csv'], key="up_mat_cepheus"
        )
    with col2:
        archivo_odoo = st.file_uploader(
            "2. Movimientos de Stock (Odoo)", type=['xlsx', 'csv'], key="up_mat_odoo"
        )

    col_a, col_r = st.columns(2)
    with col_a:
        actividades_sel = st.multiselect(
            "Actividades a evaluar:",
            options=['SOPFIBRA', 'SOPFIBRACORP', 'SOP', 'SOPCORP'],
            default=ACTIVIDADES_FIBRA_DEFAULT,
            key="mat_actividades_sel",
        )
    with col_r:
        razones_txt = st.text_input(
            "Razón(es) de cierre que deben llevar metraje (separadas por coma):",
            value=RAZONES_EXIGEN_METRAJE_DEFAULT,
            key="mat_razones_sel",
        )

    if st.button("🚀 Cruzar Información", type="primary", use_container_width=True):
        if archivo_cepheus is None or archivo_odoo is None:
            st.warning("⚠️ Sube ambos archivos para poder cruzar la información.")
        elif not actividades_sel:
            st.warning("⚠️ Selecciona al menos una actividad.")
        else:
            with st.spinner("Cruzando Cepheus contra los movimientos de bodega..."):
                try:
                    razones = [r for r in razones_txt.split(',') if r.strip()]
                    resultado = procesar_auditoria_materiales(
                        read_file_robust(archivo_cepheus), read_file_robust(archivo_odoo),
                        actividades_sel, razones,
                    )
                    st.session_state['mat_resultado'] = resultado
                except Exception as e:
                    st.error(f"❌ Error al cruzar la información: {e}")

    # Todo el resultado vive en UNA sola llave: así nunca se muestra un
    # análisis a medias (ej. detalle de un cruce viejo con metraje en 0).
    res = st.session_state.get('mat_resultado')
    if res is None:
        return
    if res.get('version') != VERSION_RESULTADO:
        st.info("🔄 El módulo se actualizó. Presiona **Cruzar Información** de nuevo para ver los resultados.")
        return

    df_detalle = res['detalle']
    resumen = res['resumen']

    st.divider()

    # --- METRAJE REAL (no depende del filtro de actividad/razón) ---
    st.markdown("#### 📏 Metraje Real de Fibra Usado en el Periodo")
    st.caption(
        f"Metros de fibra realmente entregados según Odoo (columna **{res['col_metros']}**, unidad en metros), "
        "en TODO el periodo del archivo — sin filtrar por actividad ni razón de cierre."
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total metros de fibra usados", f"{res['total_metros']:,.0f} m")
    m2.metric(f"En {' + '.join(res['actividades'])}", f"{res['metros_actividades_evaluadas']:,.0f} m")
    m3.metric(f"En órdenes {', '.join(res['razones']).title()}", f"{res['metros_ordenes_evaluadas']:,.0f} m")
    m4.metric("Sin orden en Cepheus", f"{res['metros_sin_orden_cepheus']:,.0f} m")
    if res['metros_sin_orden_cepheus'] > 0:
        st.caption(
            "ℹ️ \"Sin orden en Cepheus\" son movimientos de bodega cuyo número de orden no aparece en el "
            "rep_actividades subido — normalmente porque los dos archivos no cubren exactamente las mismas fechas."
        )
    col_mp1, col_mp2 = st.columns(2)
    with col_mp1:
        st.markdown("**Por tipo de fibra**")
        st.dataframe(res['metraje_por_producto'], use_container_width=True, hide_index=True)
    with col_mp2:
        st.markdown("**Por actividad**")
        st.dataframe(res['metraje_por_actividad'], use_container_width=True, hide_index=True)

    st.markdown("**Por técnico y actividad**")
    st.caption("Separado por actividad para que el promedio por orden sea comparable: un PEXTERNO o una INSFIBRA llevan mucho más cable que un SOPFIBRA.")
    por_tecnico = res['metraje_por_tecnico']
    actividades_metraje = st.multiselect(
        "Ver actividades:",
        options=list(res['metraje_por_actividad']['ACTIVIDAD']),
        default=list(res['metraje_por_actividad']['ACTIVIDAD']),
        key="mat_filtro_actividad_metraje",
    )
    st.dataframe(
        por_tecnico[por_tecnico['ACTIVIDAD'].isin(actividades_metraje)],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    # --- USO DE CAJAS MOLEX ---
    mostrar_uso_molex(res)

    # --- PRUEBA PILOTO: IA SOBRE LOS COMENTARIOS DE CIERRE ---
    mostrar_piloto_ia(res)

    st.divider()

    # --- AUDITORÍA DE LA RAZÓN DE CIERRE ---
    st.markdown(f"#### 🧾 Órdenes cerradas como: {', '.join(res['razones'])}")
    total = len(df_detalle)
    if total == 0:
        st.info("No se encontraron órdenes que coincidan con las actividades y razones de cierre seleccionadas.")
        return

    sin_metraje = int(df_detalle['SIN_METRAJE'].sum())
    con_metraje = total - sin_metraje
    mencionan_reserva = int(df_detalle['MENCIONA_RESERVA'].sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Órdenes evaluadas", total)
    c2.metric("Con metraje real", con_metraje)
    c3.metric("Sin metraje (mal depuradas)", sin_metraje, delta=f"{sin_metraje / total * 100:.0f}%", delta_color="inverse")
    c4.metric("Mencionan 'reserva' sin metraje", mencionan_reserva)

    st.markdown("#### 📋 Resumen por Técnico")
    st.dataframe(resumen, use_container_width=True, hide_index=True)

    st.markdown("#### 🔎 Detalle de Órdenes")
    solo_sospechosas = st.checkbox(
        "Mostrar solo órdenes sin metraje (sospechosas)", value=True, key="mat_solo_sospechosas"
    )
    df_mostrar = df_detalle[df_detalle['SIN_METRAJE']] if solo_sospechosas else df_detalle
    st.dataframe(
        df_mostrar.sort_values('MENCIONA_RESERVA', ascending=False),
        use_container_width=True,
        hide_index=True,
    )

    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            resumen.to_excel(writer, sheet_name='Resumen por Tecnico', index=False)
            df_detalle.to_excel(writer, sheet_name='Detalle Ordenes', index=False)
            res['metraje_por_producto'].to_excel(writer, sheet_name='Metraje Real x Producto', index=False)
            res['metraje_por_actividad'].to_excel(writer, sheet_name='Metraje Real x Actividad', index=False)
            res['metraje_por_tecnico'].to_excel(writer, sheet_name='Metraje Real x Tecnico', index=False)
            res['molex_por_tecnico'].to_excel(writer, sheet_name='Molex por Tecnico', index=False)
            res['molex'].to_excel(writer, sheet_name='Uso de Molex', index=False)
        st.download_button(
            "⬇️ Descargar Excel (Resumen + Detalle)",
            data=buffer.getvalue(),
            file_name="auditoria_materiales_sopfibra.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_mat_excel",
            use_container_width=True,
            on_click="ignore",
        )
    with col_dl2:
        from tools import generar_pdf_auditoria_materiales, boton_descarga
        boton_descarga(
            "⬇️ Descargar Reporte PDF",
            partial(generar_pdf_auditoria_materiales, res),
            "auditoria_materiales_sopfibra.pdf",
            key="dl_mat_pdf",
            use_container_width=True,
        )
