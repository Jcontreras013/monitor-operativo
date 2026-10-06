# ==============================================================================
# IA (Claude, de Anthropic) PARA LEER COMENTARIOS DE CIERRE
# ==============================================================================
# Prueba piloto: en vez de reglas de palabras (que fallan con "se fusiona en
# una molex", "molex nuevamente", faltas de ortografía o la ñ dañada como
# "¿"), el modelo lee el comentario de cierre y devuelve datos fijos: qué
# pasó con la molex, qué trabajo de fibra hubo, cuántos metros declara el
# técnico y si eso cuadra con la razón de cierre.
#
# La clave va SOLO en los secretos (el repo es público):
#   [anthropic]
#   api_key = "sk-ant-..."
#
# Al modelo se le manda solo la actividad, la razón de cierre y el comentario:
# nunca el nombre, teléfono ni dirección del cliente.
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

MODELO_IA = "claude-opus-5-5"
# Si el modelo declina una solicitud, la API la reintenta sola en otro modelo
# (elegido por Anthropic según el motivo) en vez de devolver el rechazo.
BETA_FALLBACK = "server-side-fallback-2026-07-01"

# Precio en USD por millón de tokens (lista de Anthropic para claude-opus-5-5).
# La escritura en caché cuesta 1.25 veces la entrada normal.
PRECIOS_USD_POR_MILLON = {"entrada": 4.00, "salida": 20.00, "cache_escritura": 5.00, "cache_lectura": 0.20}

MOLEX_OPCIONES = {
    "nueva_en_medio": "Molex nueva en medio del tramo",
    "reemplazo_casa": "Molex nueva en la casa (reemplazo)",
    "molex_de_la_casa": "Molex de la casa (ya depurada en la instalación)",
    "no_dice_donde": "Menciona molex sin decir dónde",
    "no_menciona": "No menciona molex",
}
TRABAJO_OPCIONES = {
    "cambio_completo": "Cambio completo de acometida",
    "cambio_de_tramo": "Cambio de un tramo / reparación con empalme",
    "solo_reserva": "Solo corrió reserva (sin fibra nueva)",
    "sin_fibra_nueva": "Sin fibra nueva (conector, ONU, niveles...)",
    "no_claro": "No queda claro",
}

ESQUEMA_CIERRE = {
    "type": "object",
    "properties": {
        "molex": {"type": "string", "enum": list(MOLEX_OPCIONES)},
        "trabajo_fibra": {"type": "string", "enum": list(TRABAJO_OPCIONES)},
        "metros_mencionados": {"type": "boolean"},
        "metros_declarados": {"type": "integer"},
        "razon_coincide": {"type": "boolean"},
        "evidencia": {"type": "string"},
        "observacion": {"type": "string"},
    },
    "required": ["molex", "trabajo_fibra", "metros_mencionados", "metros_declarados",
                 "razon_coincide", "evidencia", "observacion"],
    "additionalProperties": False,
}

# Fijo y sin datos variables: así se guarda en caché y las siguientes
# solicitudes lo cobran a una fracción del precio.
INSTRUCCIONES = """Eres auditor de cierres de órdenes de MAXCOM, un proveedor de internet y cable por fibra óptica (FTTH) en Honduras. Recibes el comentario de cierre que escribió un técnico en Cepheus y devuelves datos fijos sobre lo que realmente hizo. Los comentarios vienen con faltas de ortografía, sin puntuación y a veces con letras dañadas ("da¿o" es "daño", "se¿al" es "señal", "lla" es "ya", "iso la vicita" es "hizo la visita"). Interprétalos como lo haría un supervisor de campo.

## Molex (campo "molex")
Toda casa ya tiene su caja molex desde la instalación (INSFIBRA), y esa se depuró en ese momento. La que se gasta en un soporte es una molex NUEVA puesta EN MEDIO del tramo, entre la mufa y la casa, para empalmar.
- "nueva_en_medio": el técnico puso una molex nueva para empalmar en el camino ("se le añadió una molex", "se le puso una molex temporal", "se hizo una molex provisional", "molex en medio", "empalme con molex en el poste").
- "reemplazo_casa": puso una molex nueva en la casa porque la anterior ya no estaba o estaba destruida ("se dejó molex en la casa ya que no se encontró la que tenían").
- "molex_de_la_casa": trabajó en la molex que ya estaba ("fibra dañada en la molex, se preparó y se fusiona", "se fusiona en la molex", "hasta una molex que ya estaba", "se arma la molex nuevamente", "el cliente tenía una molex", "se eliminó la molex").
- "no_dice_donde": menciona una molex pero no se puede saber si era nueva o la existente ("se fusiona en una molex" sin más contexto).
- "no_menciona": no habla de molex.

## Trabajo de fibra (campo "trabajo_fibra")
- "cambio_completo": se tiró una acometida nueva de la mufa a la casa ("se tiró fibra", "nuevo lanzamiento de fibra", "se cambió la fibra completa", con punta inicial y final).
- "cambio_de_tramo": se cambió solo una parte o se hizo una reparación con empalme, incluida la provisional ("se cambió un tramo", "reparación provisional").
- "solo_reserva": se corrió reserva o se reubicó la fibra existente, sin fibra nueva ("se corrió reserva y se fusiona").
- "sin_fibra_nueva": no se tocó la acometida: conector, pigtail, patch cord, ONU, limpieza, niveles, configuración, o solo se refusionó.
- "no_claro": el comentario no permite saberlo.

## Metros (campos "metros_mencionados" y "metros_declarados")
Metros de fibra NUEVA que dice haber usado. Si da punta inicial y punta final, es la diferencia (punta inicial 1000, punta final 950 = 50). Si dice "usando 65 mts", son 65. Si no dice metros, "metros_mencionados" es false y "metros_declarados" es 0. No inventes cifras.

## Razón de cierre (campo "razon_coincide")
"CORTE DE ACOMETIDA" significa que se cambió fibra: coincide solo con "cambio_completo" o "cambio_de_tramo". Con "solo_reserva" o "sin_fibra_nueva" NO coincide. Para otras razones de cierre, marca false solo si el comentario la contradice claramente.

## Evidencia y observación
- "evidencia": copia textual (máximo 25 palabras) del fragmento del comentario que justifica tu respuesta sobre molex y trabajo de fibra.
- "observacion": una frase corta, en español, solo si hay algo que un supervisor deba revisar; si no, cadena vacía.
"""


def _texto_orden(actividad, razon, comentario):
    return (f"Actividad: {actividad}\n"
            f"Razón de cierre: {razon}\n"
            f"Comentario de cierre:\n<<<\n{comentario}\n>>>")


def costo_usd(uso):
    """Costo en USD de un dict de uso (tokens)."""
    p = PRECIOS_USD_POR_MILLON
    return (uso.get("entrada", 0) * p["entrada"] + uso.get("salida", 0) * p["salida"]
            + uso.get("cache_escritura", 0) * p["cache_escritura"]
            + uso.get("cache_lectura", 0) * p["cache_lectura"]) / 1_000_000


def _uso(respuesta):
    u = respuesta.usage
    return {
        "entrada": getattr(u, "input_tokens", 0) or 0,
        "salida": getattr(u, "output_tokens", 0) or 0,
        "cache_escritura": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_lectura": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def crear_cliente(api_key):
    import anthropic
    # La SDK reintenta sola los 429/5xx y los cortes de red.
    return anthropic.Anthropic(api_key=api_key, max_retries=4, timeout=120.0)


def clasificar_cierre(cliente, actividad, razon, comentario, effort="low"):
    """
    Lee un comentario de cierre. Devuelve (datos | None, uso_tokens, error | None).
    `effort` controla cuánto razona el modelo: "low" basta para clasificar.
    """
    respuesta = cliente.beta.messages.create(
        model=MODELO_IA,
        max_tokens=4000,
        betas=[BETA_FALLBACK],
        fallbacks="default",
        system=[{"type": "text", "text": INSTRUCCIONES, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": ESQUEMA_CIERRE}},
        messages=[{"role": "user", "content": _texto_orden(actividad, razon, comentario)}],
    )
    uso = _uso(respuesta)
    if respuesta.stop_reason == "refusal":
        return None, uso, "el modelo no respondió esta orden (rechazo)"
    if respuesta.stop_reason == "max_tokens":
        return None, uso, "respuesta incompleta (se acabó el límite de tokens)"
    texto = next((b.text for b in respuesta.content if b.type == "text"), "")
    try:
        return json.loads(texto), uso, None
    except json.JSONDecodeError:
        return None, uso, "respuesta sin formato válido"


def ejecutar_piloto(df_ordenes, api_key, effort="low", hilos=4, al_avanzar=None):
    """
    Corre la IA sobre las órdenes (columnas ORDEN, ACTIVIDAD, RAZON_CIERRE,
    COMENTARIO). Devuelve (df_resultados, resumen). Un error de autenticación
    detiene todo; cualquier otro queda anotado en la fila.
    """
    import anthropic

    cliente = crear_cliente(api_key)
    filas = df_ordenes.to_dict("records")
    resultados, uso_total = {}, {"entrada": 0, "salida": 0, "cache_escritura": 0, "cache_lectura": 0}
    inicio = time.time()

    def trabajo(fila):
        comentario = "" if pd.isna(fila.get("COMENTARIO")) else str(fila.get("COMENTARIO"))
        try:
            return clasificar_cierre(cliente, fila.get("ACTIVIDAD", ""), fila.get("RAZON_CIERRE", ""), comentario, effort)
        except anthropic.AuthenticationError:
            raise  # clave inválida: no tiene sentido seguir
        except Exception as e:
            return None, {}, str(e)[:200]

    if not filas:
        return pd.DataFrame(), {"ordenes": 0, "errores": 0, "segundos": 0, "uso": uso_total,
                                "costo_usd": 0.0, "modelo": MODELO_IA, "effort": effort}

    # La primera orden va sola: escribe las instrucciones en la caché (las
    # siguientes ya las leen de ahí) y, si la clave está mal, se sabe con una
    # sola llamada.
    resultados[0] = trabajo(filas[0])
    if al_avanzar:
        al_avanzar(1, len(filas))
    with ThreadPoolExecutor(max_workers=hilos) as ejecutor:
        futuros = {ejecutor.submit(trabajo, fila): i for i, fila in enumerate(filas) if i > 0}
        for hechas, futuro in enumerate(as_completed(futuros), start=2):
            resultados[futuros[futuro]] = futuro.result()
            if al_avanzar:
                al_avanzar(hechas, len(filas))

    salida = []
    for i, fila in enumerate(filas):
        datos, uso, error = resultados.get(i, (None, {}, "sin resultado"))
        for k in uso_total:
            uso_total[k] += uso.get(k, 0)
        datos = datos or {}
        salida.append({
            "ORDEN": fila["ORDEN"],
            "IA_MOLEX": MOLEX_OPCIONES.get(datos.get("molex"), ""),
            "IA_TRABAJO_FIBRA": TRABAJO_OPCIONES.get(datos.get("trabajo_fibra"), ""),
            "IA_METROS_DECLARADOS": (datos.get("metros_declarados") if datos.get("metros_mencionados") else None),
            "IA_RAZON_COINCIDE": datos.get("razon_coincide"),
            "IA_EVIDENCIA": datos.get("evidencia", ""),
            "IA_OBSERVACION": datos.get("observacion", ""),
            "IA_ERROR": error or "",
            "IA_COSTO_USD": round(costo_usd(uso), 5),
        })
    resumen = {
        "ordenes": len(filas),
        "errores": sum(1 for s in salida if s["IA_ERROR"]),
        "segundos": round(time.time() - inicio, 1),
        "uso": uso_total,
        "costo_usd": round(costo_usd(uso_total), 4),
        "modelo": MODELO_IA,
        "effort": effort,
    }
    return pd.DataFrame(salida), resumen
