import streamlit as st
import os
import tempfile
from tools import safestr

# --- IMPORTACIÓN BLINDADA PARA FPDF2 ---
try:
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Falta la librería FPDF. Asegúrate de que 'fpdf2' esté en tu requirements.txt")

# ==============================================================================
# CONTENIDO DEL MANUAL DE USUARIO
# ==============================================================================
# FUENTE ÚNICA del manual. De esta estructura salen LAS DOS versiones: la que se
# lee en pantalla y el PDF descargable. Antes el contenido estaba escrito a mano
# dentro de las llamadas a FPDF, así que para corregir una frase había que tocar
# el código de dibujado y no existía versión en pantalla: había que descargar el
# PDF para leer cualquier cosa.
#
# Para editar el manual se edita SOLO esta lista. Tipos de bloque admitidos:
#   ("sub",    "Subtítulo")
#   ("p",      "Un párrafo")
#   ("lista",  ["punto", "punto"])
#   ("pasos",  ["primer paso", "segundo paso"])       -> numerados
#   ("aviso",  "info"|"warning", "Texto del recuadro")
#   ("tabla",  ["Encabezado", ...], [["celda", ...], ...])
#
# OJO con el PDF: usa fuentes latin-1, así que los emoji y algunos símbolos se
# eliminan al exportar (ver safestr). El texto debe entenderse sin ellos.

MANUAL_VERSION = "Septiembre 2026"

MANUAL_SECCIONES = [
    {
        "titulo": "1. Entrar al sistema",
        "intro": "El acceso es con usuario y contraseña. Lo que ves adentro depende del rol que tenga tu usuario asignado.",
        "bloques": [
            ("pasos", [
                "Abre el monitor en Chrome o Safari. No lo abras dentro de WhatsApp ni de WATI: esos navegadores internos bloquean las descargas de PDF y Excel.",
                "Escribe tu usuario y contraseña y presiona 'Ingresar'.",
                "Listo. Abajo en la barra lateral vas a ver tu nombre y tu rol.",
            ]),
            ("aviso", "warning",
             "La sesión se cierra sola tras 30 minutos sin actividad. Es a propósito, por seguridad. Si te saca, vuelve a entrar con normalidad."),
            ("sub", "Qué ve cada rol"),
            ("tabla",
             ["Módulo", "Admin", "Jefe", "Monitoreo", "Llamados"],
             [
                 ["Monitor en Vivo", "Sí", "Sí", "Sí", "No"],
                 ["Centro de Reportes", "Sí", "Sí", "No", "No"],
                 ["Control Calidad", "Sí", "Sí", "Sí", "No"],
                 ["Reprog / No Inst", "Sí", "Sí", "No", "No"],
                 ["Auditoría Vehículos", "Sí", "Sí", "No", "No"],
                 ["Configuración", "Sí", "Sí", "No", "No"],
                 ["Expedientes", "Sí", "Sí", "No", "Solo esto"],
                 ["Orden manual y almuerzo", "Sí", "Sí", "No", "No"],
                 ["Forzar actualización / FTTX", "Sí", "No", "No", "No"],
             ]),
            ("aviso", "info",
             "Si a alguien le falta un módulo: que mire abajo en la barra lateral, junto al botón de cerrar sesión, donde dice 'Usuario ... | Rol ...'. Si el rol que aparece no es el que debería tener, hay que corregir el acceso. A veces basta con cerrar sesión y volver a entrar, porque el rol viaja dentro de la sesión y una sesión vieja arrastra el rol viejo."),
        ],
    },
    {
        "titulo": "2. Cómo está organizada la pantalla",
        "intro": "Dos zonas: la barra lateral izquierda para navegar y registrar cosas, y el área central donde trabajas.",
        "bloques": [
            ("sub", "Barra lateral"),
            ("lista", [
                "MENÚ DE CONTROL: eliges el módulo. Está arriba de todo.",
                "Ingresar Orden Manual: para una orden real que la API no reflejó. Solo admin y jefe.",
                "Registrar Almuerzo: marca el bloque de almuerzo del técnico en el Gantt.",
                "Sincronización: 'ACTUALIZAR DESDE LA NUBE' trae los datos más recientes.",
                "Carga de Archivos: subir el rep_actividades cuando toca procesarlo a mano.",
                "Cerrar Sesión: al final. Ahí mismo se ve tu usuario y tu rol.",
            ]),
            ("aviso", "info",
             "Los filtros de la barra lateral se quedan puestos aunque cambies de pestaña. Si de pronto faltan órdenes que esperabas ver, revisa primero si dejaste un filtro activo. El sistema avisa arriba de la tabla cuando un filtro está escondiendo categorías completas."),
        ],
    },
    {
        "titulo": "3. Monitor en Vivo",
        "intro": "La pantalla del día a día. Muestra qué está pasando ahora mismo con las órdenes y los técnicos. Tiene tres pestañas: PANEL OPERATIVO, PRODUCTIVIDAD y ANALÍTICA.",
        "bloques": [
            ("sub", "Panel Operativo"),
            ("p", "Arriba hay tres botones que cambian lo que muestra la tabla:"),
            ("lista", [
                "ASIGNADAS ACTIVAS: órdenes vivas, todavía sin cerrar.",
                "CERRADAS HOY: lo que se liquidó en la jornada.",
                "ANULADAS HOY: órdenes anuladas hoy.",
            ]),
            ("p", "Abajo está el Panel de Control y Análisis Detallado, la tabla grande con todas las órdenes. Cada columna trae su propia caja de filtro debajo del encabezado: escribes ahí y la tabla se filtra al instante. Para ver todas las columnas, incluidas OLT y PON, usa la barra de desplazamiento horizontal de abajo."),
            ("p", "La primera columna tiene un recuadro de selección. Al marcarlo se abre la ventana de detalle de esa orden, con los datos del cliente, los tiempos y el comentario. Marcas solo el recuadro; si quieres copiar texto de una celda, puedes hacerlo sin que se abra nada."),
            ("sub", "Los colores de la tabla"),
            ("tabla",
             ["Color", "Dónde", "Qué significa"],
             [
                 ["Rojo", "Columna NUM", "El cliente está offline (equipo caído)"],
                 ["Ámbar", "Columna HORA_INI", "Lleva más de 2 horas abierta sin cerrarse"],
                 ["Verde", "TIEMPO_REAL", "Se cerró en menos de 1 hora"],
                 ["Rojo", "TIEMPO_REAL", "Tardó más de 2 horas en cerrarse"],
                 ["Verde a rojo", "DIAS_RETRASO", "Días que lleva la orden: verde al día, rojo 7 o más"],
             ]),
            ("sub", "Línea de tiempo operativa (Gantt)"),
            ("p", "Una barra por cada orden, agrupadas por técnico, sobre el reloj del día. Sirve para ver de un golpe quién está trabajando, quién tiene huecos y dónde se concentran los tiempos muertos."),
            ("lista", [
                "Las órdenes abiertas se estiran hasta la hora actual.",
                "Las órdenes que vienen abiertas de días anteriores se muestran solo si activas la casilla correspondiente. Su barra arranca al inicio de la jornada, porque el trabajo de días previos no cabe en la línea de hoy.",
                "El almuerzo aparece como un bloque aparte, si se registró desde la barra lateral.",
            ]),
        ],
    },
    {
        "titulo": "4. Centro de Reportes",
        "intro": "Cuatro pestañas. Aquí se sacan los PDF y se analiza la red.",
        "bloques": [
            ("lista", [
                "Cierre Diario: el resumen de la jornada y el PDF de cierre. Es el reporte que se manda al final del día.",
                "Pendientes Generales: todo lo que quedó abierto, con indicadores de mora. Sirve para priorizar el día siguiente.",
                "Análisis de Red (OLT/PON): dónde se concentran las fallas dentro de la red.",
                "Diagnóstico de Offline: por qué se caen los clientes. Ver la sección 5.",
            ]),
            ("sub", "Análisis de Red (OLT/PON)"),
            ("p", "Responde dónde está el problema. La idea de fondo: varios reportes de clientes distintos en el mismo puerto PON y en una ventana corta de tiempo casi nunca son fallas independientes. Normalmente es un solo daño físico visto desde muchos clientes."),
            ("lista", [
                "Desglose OLT / PON: cuántas incidencias por equipo y por puerto, mes a mes.",
                "Eventos masivos: agrupa incidencias del mismo PON ocurridas juntas en el tiempo. Si aparece un evento, atiende la causa en vez de despachar un técnico por cada llamada.",
                "Colonia por PON: si una colonia concentra fallas de un solo PON, el problema es de red; si son de varios PON, apunta a algo externo (obra, clima, energía).",
            ]),
        ],
    },
    {
        "titulo": "5. Diagnóstico de Offline",
        "intro": "Responde por qué aparecen tantos offline, leyendo lo que el técnico escribió al cerrar la orden.",
        "bloques": [
            ("p", "Lo primero que ves arriba es la Lectura del periodo: el módulo redacta las conclusiones en español llano con los números reales. Se puede leer tal cual en una reunión o copiar a un correo."),
            ("sub", "Los tres números de arriba"),
            ("lista", [
                "Soportes analizados: cuántas averías de fibra se atendieron en el periodo. Es el universo del que sale todo lo demás.",
                "Cobertura: de cada 100 órdenes, en cuántas el técnico escribió algo en el cierre que permita saber qué pasó. Es el número más importante del módulo.",
                "Falsos positivos: el técnico llegó y el equipo estaba funcionando. No había falla; es un viaje que no correspondía.",
            ]),
            ("aviso", "warning",
             "Si la cobertura baja del 60 por ciento, el módulo te lo advierte en pantalla. Eso no significa que el análisis falló: significa que los cierres no traen suficiente detalle. La solución no es más analítica, es exigir que el técnico escriba qué encontró al cerrar la orden."),
            ("sub", "Las causas y qué significa cada una"),
            ("tabla",
             ["Causa", "Qué significa operativamente"],
             [
                 ["Falso positivo", "NO es falla. Infla el conteo y cuesta una visita."],
                 ["Corte administrativo / mora", "NO es falla técnica. Es cobranza."],
                 ["Daño externo / corte de fibra", "RECO, poda, poste, obra, accidente. Ni del cliente ni del técnico."],
                 ["Instalación deficiente / retrabajo", "El dato más incómodo y más rentable: apunta a quien instaló."],
                 ["Energía / sin corriente", "Sin luz, breaker, batería, UPS."],
                 ["Equipo del cliente (ONU/ONT)", "Equipo quemado, rayo, cliente lo desconectó."],
                 ["Falla de red / OLT", "Tarjeta, puerto PON, splitter. Se arregla una vez para muchos."],
                 ["Nivel óptico / atenuación", "Conector sucio, empalme, curvatura, potencia fuera de rango."],
                 ["No hubo acceso", "No se pudo entrar. No se diagnosticó nada."],
                 ["Sin clasificar", "Hay texto, pero no dice qué se encontró ('reparado' a secas)."],
                 ["Sin comentario de cierre", "El técnico cerró sin escribir nada."],
             ]),
            ("aviso", "info",
             "En la pestaña Detalle auditable, la columna EVIDENCIA muestra las palabras exactas del cierre que dispararon cada clasificación. Si algo quedó mal clasificado, ahí se ve por qué. Filtra por 'Sin clasificar' para leer qué están escribiendo realmente los técnicos."),
        ],
    },
    {
        "titulo": "6. Expedientes del personal",
        "intro": "Registro de incidencias, llamados de atención, méritos y documentos del personal. Tiene una pestaña de Operaciones (técnicos y auxiliares) y otra Administrativa (SAC, Ventas, Bodega, Contabilidad, Administración).",
        "bloques": [
            ("sub", "Registrar una incidencia administrativa"),
            ("pasos", [
                "Elige el Área o Departamento. Al elegirla se cargan los colaboradores de esa área.",
                "Elige el colaborador y el tipo de registro.",
                "Pon la fecha del evento, adjunta evidencias si hay, y escribe la descripción de los hechos.",
                "Presiona REGISTRAR INCIDENCIA ADMINISTRATIVA.",
            ]),
            ("aviso", "info",
             "Llegada tardía y ausencia son DOS tipos de registro separados. Antes compartían una sola opción y no se podía distinguir quién llegó tarde de quién no se presentó. Los registros viejos que quedaron con el motivo combinado se separan solos leyendo el comentario, así que el histórico también sale dividido."),
            ("sub", "Sacar el reporte por área"),
            ("p", "En la pestaña Administrativo hay un selector de Área. Al elegir un área (SAC, Bodega, Administración) el historial, los indicadores y el PDF o Word salen solo de ese departamento. Con TODAS LAS ÁREAS se muestra además el conteo de registros por área."),
            ("p", "Para descargar, presiona Preparar PDF o Preparar Word y el botón de descarga aparece ahí mismo."),
            ("sub", "Cómo se clasifican las faltas"),
            ("lista", [
                "Tres o más llegadas tarde del mismo colaborador promueven la falta a GRAVE por reincidencia.",
                "Una ausencia sin aviso o sin justificar sale GRAVE; una ausencia simple queda LEVE.",
            ]),
        ],
    },
    {
        "titulo": "7. Tareas frecuentes",
        "bloques": [
            ("sub", "Ingresar una orden manual"),
            ("p", "Se usa cuando la API falla y una orden real de un técnico no aparece en el monitor."),
            ("pasos", [
                "En la barra lateral, abre 'Ingresar Orden Manual'.",
                "Escribe el número de orden y elige actividad y técnico.",
                "Pon la fecha y la hora de inicio en formato HH:MM de 24 horas (ejemplo: 08:00).",
                "La hora liquidada se deja VACÍA si la orden sigue abierta.",
                "Presiona Guardar Orden Manual. La orden aparece en el monitor y en el Gantt como cualquier otra.",
            ]),
            ("aviso", "warning",
             "Si al guardar aparece un aviso de que no se pudo respaldar en la nube, la orden quedó guardada solo en este servidor y se va a perder si la aplicación se reinicia. Vuelve a guardarla más tarde. Si no aparece ese aviso, la orden ya quedó respaldada y sobrevive a los reinicios."),
            ("sub", "Registrar un almuerzo"),
            ("p", "Eliges el técnico y la hora de inicio y fin. Ese bloque aparece en el Gantt del día, para que el hueco en la línea de tiempo no se lea como tiempo muerto."),
            ("sub", "Actualizar los datos"),
            ("lista", [
                "ACTUALIZAR DESDE LA NUBE: lo normal. Trae lo último que se sincronizó.",
                "FORZAR ACTUALIZACIÓN INMEDIATA: solo admin, cuando se necesita bajar de la API en el momento.",
                "Carga de Archivos: subir el rep_actividades a mano cuando la API está caída.",
            ]),
        ],
    },
    {
        "titulo": "8. Reglas del sistema que conviene conocer",
        "intro": "Cuatro reglas que explican la mayoría de las dudas del tipo '¿por qué no me sale esta orden?'.",
        "bloques": [
            ("sub", "La jornada operativa empieza a las 6:00"),
            ("p", "Para decidir a qué día pertenece una orden, el sistema no usa la medianoche sino las 6:00 de la mañana. Una orden cerrada a las 02:00 cuenta en la jornada del día anterior, no en la que apenas empieza. Es intencional y es lo que hace que los números del cierre diario cuadren con la realidad del turno."),
            ("sub", "Qué cuenta como offline"),
            ("p", "Una orden se marca como offline cuando cumple las TRES condiciones: está abierta, es de actividad SOPFIBRA, y el comentario menciona equipo caído (ONU OFFLINE, LOS EN ROJO, PON ROJO y similares). Si el comentario dice que ya se recuperó, deja de contar."),
            ("p", "Las instalaciones y los trabajos de planta externa nunca cuentan como offline, aunque su texto lo mencione: no son averías."),
            ("sub", "Solo se muestran actividades reales de campo"),
            ("p", "El sistema trabaja con una lista fija de actividades válidas (SOPFIBRA, INSFIBRA, PEXTERNO, CEQUI y demás). Cualquier actividad fuera de esa lista queda descartada desde la raíz y no aparece en ninguna vista. Si falta una actividad que debería verse, hay que agregarla a esa lista."),
            ("sub", "Una orden entra al Gantt solo si tiene hora de inicio"),
            ("p", "El Gantt representa trabajo realizado. Una orden asignada pero que el técnico todavía no inició no tiene hora de inicio real, y dibujarla implicaría inventar un horario que nunca ocurrió. Por eso no aparece."),
        ],
    },
    {
        "titulo": "9. Si algo no funciona",
        "bloques": [
            ("tabla",
             ["Síntoma", "Qué revisar"],
             [
                 ["Faltan órdenes en la tabla", "Filtros activos en la barra lateral. El sistema avisa arriba de la tabla cuando un filtro esconde categorías completas."],
                 ["No veo las columnas OLT y PON", "Están más a la derecha. Usa la barra de desplazamiento horizontal debajo de la tabla."],
                 ["No aparecen los filtros por columna", "Si en su lugar sale un aviso amarillo, el módulo de filtros no se instaló en el servidor: revisar el log de despliegue."],
                 ["A un usuario le falta un módulo", "Que revise su rol en la barra lateral. Si está mal, corregir el acceso; si acaba de cambiar, que cierre sesión y vuelva a entrar."],
                 ["La orden manual desapareció", "Fíjate si al guardarla salió el aviso de que no se pudo respaldar en la nube. Vuelve a ingresarla."],
                 ["No puedo descargar el PDF en el celular", "Abre el monitor en Chrome o Safari. Dentro de WhatsApp o WATI las descargas se bloquean."],
                 ["Me sacó del sistema", "Normal tras 30 minutos sin actividad. Vuelve a entrar."],
                 ["Los datos se ven viejos", "Presiona ACTUALIZAR DESDE LA NUBE. Si sigue igual, un admin puede forzar la actualización."],
             ]),
        ],
    },
]


# ==============================================================================
# RENDERIZADO EN PANTALLA
# ==============================================================================
def _mostrar_manual_en_pantalla():
    """Dibuja el manual dentro de la app, sin necesidad de descargar nada."""
    for i, seccion in enumerate(MANUAL_SECCIONES):
        with st.expander(seccion["titulo"], expanded=(i == 0)):
            if seccion.get("intro"):
                st.caption(seccion["intro"])

            for bloque in seccion["bloques"]:
                tipo = bloque[0]

                if tipo == "sub":
                    st.markdown(f"**{bloque[1]}**")
                elif tipo == "p":
                    st.write(bloque[1])
                elif tipo == "lista":
                    st.markdown("\n".join(f"- {item}" for item in bloque[1]))
                elif tipo == "pasos":
                    st.markdown("\n".join(f"{n}. {item}" for n, item in enumerate(bloque[1], 1)))
                elif tipo == "aviso":
                    (st.warning if bloque[1] == "warning" else st.info)(bloque[2])
                elif tipo == "tabla":
                    encabezados, filas = bloque[1], bloque[2]
                    sep = "|".join(["---"] * len(encabezados))
                    cuerpo = "\n".join("| " + " | ".join(f) + " |" for f in filas)
                    st.markdown(f"| {' | '.join(encabezados)} |\n|{sep}|\n{cuerpo}")


# ==============================================================================
# RENDERIZADO A PDF
# ==============================================================================
class ManualPDF(FPDF):
    def header(self):
        self.set_y(8)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(110, 122, 137)
        self.cell(95, 5, "MONITOR OPERATIVO - MANUAL DE USUARIO", align="L")
        self.cell(95, 5, "DEPARTAMENTO DE CONTROL OPERATIVO", align="R", ln=True)
        self.set_draw_color(220, 226, 235)
        self.line(10, 14, 200, 14)
        self.ln(9)

    def footer(self):
        self.set_y(-15)
        self.set_draw_color(220, 226, 235)
        self.line(10, self.get_y(), 200, self.get_y())
        self.set_y(-11)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(140, 150, 163)
        self.cell(0, 5, safestr(f"Version {MANUAL_VERSION}"), align="L")
        self.cell(0, 5, f"Pagina {self.page_no()}", align="R")


def _pdf_tabla(pdf, encabezados, filas):
    """
    Tabla simple con celdas que ajustan alto segun su contenido.
    FPDF no trae tablas, asi que se dibuja fila por fila midiendo primero
    cuantas lineas ocupa la celda mas alta.
    """
    ancho_total = 190
    n = len(encabezados)
    # La primera columna suele ser la etiqueta corta; el resto reparte el sobrante.
    if n == 2:
        anchos = [70, 120]
    elif n == 3:
        anchos = [32, 48, 110]
    else:
        anchos = [ancho_total - (n - 1) * 24] + [24] * (n - 1)

    alto_linea = 4.6

    def alto_de_fila(celdas):
        maximo = 1
        for texto, ancho in zip(celdas, anchos):
            lineas = len(pdf.multi_cell(ancho, alto_linea, safestr(texto), split_only=True))
            maximo = max(maximo, lineas)
        return maximo * alto_linea + 2

    # Encabezado
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(238, 242, 248)
    pdf.set_text_color(50, 62, 78)
    alto = alto_de_fila(encabezados)
    y0 = pdf.get_y()
    x = 10
    for texto, ancho in zip(encabezados, anchos):
        pdf.set_xy(x, y0)
        pdf.multi_cell(ancho, alto_linea, safestr(texto), border=0, fill=True)
        x += ancho
    pdf.set_xy(10, y0 + alto)

    # Filas
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(35, 44, 56)
    for fila in filas:
        alto = alto_de_fila(fila)
        if pdf.get_y() + alto > 275:
            pdf.add_page()
        y0 = pdf.get_y()
        x = 10
        for texto, ancho in zip(fila, anchos):
            pdf.set_xy(x, y0)
            pdf.multi_cell(ancho, alto_linea, safestr(texto), border=0)
            x += ancho
        pdf.set_draw_color(228, 233, 241)
        pdf.line(10, y0 + alto - 1, 200, y0 + alto - 1)
        pdf.set_xy(10, y0 + alto)
    pdf.ln(3)


def generar_manual_pdf():
    """Compila el PDF a partir de MANUAL_SECCIONES, la misma fuente que la vista en pantalla."""
    pdf = ManualPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(10, 10, 10)

    # --- Portada ---
    pdf.add_page()
    pdf.ln(24)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(20, 26, 36)
    pdf.multi_cell(190, 11, safestr("Manual del Monitor Operativo"), align="C")
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(90, 102, 118)
    pdf.multi_cell(190, 6, safestr(
        "Como usar el sistema dia a dia: seguir las ordenes en curso, entender por que "
        "se caen los clientes, sacar los reportes y registrar los expedientes del personal."
    ), align="C")
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(120, 131, 146)
    pdf.multi_cell(190, 5.5, safestr(
        f"Version {MANUAL_VERSION}   |   Fuente de datos: Cepheus   |   Zona horaria: UTC-6"
    ), align="C")

    pdf.ln(14)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(31, 82, 196)
    pdf.cell(190, 7, safestr("CONTENIDO"), ln=True, align="C")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(60, 71, 86)
    for seccion in MANUAL_SECCIONES:
        pdf.cell(190, 5.8, safestr(seccion["titulo"]), ln=True, align="C")

    # --- Secciones ---
    for seccion in MANUAL_SECCIONES:
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 15)
        pdf.set_text_color(20, 26, 36)
        pdf.multi_cell(190, 8, safestr(seccion["titulo"]))
        pdf.ln(1)

        if seccion.get("intro"):
            pdf.set_font("Helvetica", "I", 9.5)
            pdf.set_text_color(95, 107, 123)
            pdf.multi_cell(190, 5, safestr(seccion["intro"]))
            pdf.ln(3)

        for bloque in seccion["bloques"]:
            tipo = bloque[0]

            if tipo == "sub":
                pdf.ln(2)
                pdf.set_font("Helvetica", "B", 10.5)
                pdf.set_text_color(31, 82, 196)
                pdf.multi_cell(190, 6, safestr(bloque[1]))
                pdf.ln(0.5)

            elif tipo == "p":
                pdf.set_font("Helvetica", "", 9.5)
                pdf.set_text_color(35, 44, 56)
                pdf.multi_cell(190, 5, safestr(bloque[1]))
                pdf.ln(2)

            elif tipo == "lista":
                pdf.set_font("Helvetica", "", 9.5)
                pdf.set_text_color(35, 44, 56)
                for item in bloque[1]:
                    pdf.set_x(14)
                    pdf.multi_cell(186, 5, safestr(f"-  {item}"))
                    pdf.ln(0.6)
                pdf.ln(1.6)

            elif tipo == "pasos":
                pdf.set_font("Helvetica", "", 9.5)
                pdf.set_text_color(35, 44, 56)
                for n, item in enumerate(bloque[1], 1):
                    pdf.set_x(14)
                    pdf.multi_cell(186, 5, safestr(f"{n}.  {item}"))
                    pdf.ln(0.6)
                pdf.ln(1.6)

            elif tipo == "aviso":
                es_alerta = bloque[1] == "warning"
                if pdf.get_y() > 250:
                    pdf.add_page()
                y0 = pdf.get_y()
                pdf.set_font("Helvetica", "", 9.5)
                pdf.set_fill_color(250, 238, 231) if es_alerta else pdf.set_fill_color(231, 237, 252)
                pdf.set_text_color(35, 44, 56)
                pdf.set_x(13)
                pdf.multi_cell(187, 5, safestr(bloque[2]), fill=True)
                pdf.set_draw_color(158, 67, 24) if es_alerta else pdf.set_draw_color(31, 82, 196)
                pdf.set_line_width(0.9)
                pdf.line(11, y0, 11, pdf.get_y())
                pdf.set_line_width(0.2)
                pdf.ln(3)

            elif tipo == "tabla":
                if pdf.get_y() > 235:
                    pdf.add_page()
                _pdf_tabla(pdf, bloque[1], bloque[2])

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    pdf.output(path)
    with open(path, "rb") as f:
        datos = f.read()
    os.remove(path)
    return datos


# ==============================================================================
# INTERFAZ DEL MÓDULO
# ==============================================================================
def inicializar_configuracion():
    """Inicializa los valores por defecto en la sesión si no existen."""
    if 'config_ver_filtros' not in st.session_state:
        st.session_state.config_ver_filtros = True
    if 'config_ver_tablero' not in st.session_state:
        st.session_state.config_ver_tablero = True
    if 'config_ver_consolidado' not in st.session_state:
        st.session_state.config_ver_consolidado = True
    if 'config_ver_gantt' not in st.session_state:
        st.session_state.config_ver_gantt = True
    if 'config_ver_panel' not in st.session_state:
        st.session_state.config_ver_panel = True


def mostrar_configuracion():
    st.title("⚙️ Configuración y Documentación")

    tab_conf, tab_doc = st.tabs(["🎛️ Preferencias de Interfaz", "📚 Manual de Usuario"])

    with tab_conf:
        st.subheader("Personalización del Monitor en Vivo")
        st.write("Apaga o enciende las secciones que deseas ver en tu pantalla principal.")

        st.session_state.config_ver_filtros = st.toggle("🔍 Mostrar: Filtros Rápidos", value=st.session_state.config_ver_filtros)
        st.session_state.config_ver_tablero = st.toggle("📊 Mostrar: Tablero de Carga Actual (Pendientes)", value=st.session_state.config_ver_tablero)
        st.session_state.config_ver_consolidado = st.toggle("📊 Mostrar: Consolidado por Segmento (Mora vs Al Día)", value=st.session_state.config_ver_consolidado)
        st.session_state.config_ver_gantt = st.toggle("⏳ Mostrar: Línea de Tiempo Operativa (Gantt)", value=st.session_state.config_ver_gantt)
        st.session_state.config_ver_panel = st.toggle("🎛️ Mostrar: Panel de Control y Análisis Detallado", value=st.session_state.config_ver_panel)

    with tab_doc:
        st.subheader("📖 Manual de Usuario")
        st.caption(
            f"Versión {MANUAL_VERSION}. Se lee aquí mismo — abre la sección que necesites. "
            "También se puede descargar en PDF para imprimir o compartir."
        )

        col_izq, col_btn, col_der = st.columns([1, 2, 1])
        with col_btn:
            try:
                st.download_button(
                    label="📥 DESCARGAR MANUAL EN PDF",
                    data=generar_manual_pdf(),
                    file_name=f"Manual_Monitor_Operativo_{MANUAL_VERSION.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"No se pudo compilar el PDF del manual: {e}")

        st.divider()
        _mostrar_manual_en_pantalla()
