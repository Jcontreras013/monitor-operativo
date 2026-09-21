# Monitor Operativo MAXCOM

Sistema interno de MAXCOM para monitorear en tiempo real las órdenes de instalación/soporte de un ISP (fibra óptica e internet), hacer seguimiento de técnicos en campo, gestionar control de calidad, expedientes de personal (faltas/incidencias) y reportes gerenciales — todo sobre una aplicación web hecha con [Streamlit](https://streamlit.io/).

No es un producto de código abierto genérico: está construido a medida sobre los procesos de MAXCOM (integración con su API interna "Cepheus", su forma de operar SAC/Operaciones, sus plantillas de reporte). Este README documenta cómo está armado para quien le dé mantenimiento.

## Índice

- [Qué resuelve](#qué-resuelve)
- [Arquitectura](#arquitectura)
- [Módulos del sistema](#módulos-del-sistema)
- [Roles y permisos](#roles-y-permisos)
- [Requisitos](#requisitos)
- [Configuración (`secrets.toml`)](#configuración-secretstoml)
- [Cómo correrlo](#cómo-correrlo)
- [Pruebas automatizadas](#pruebas-automatizadas)
- [Despliegue en producción](#despliegue-en-producción)
- [Dónde vive cada dato](#dónde-vive-cada-dato)
- [Seguridad](#seguridad)
- [Estructura del repositorio](#estructura-del-repositorio)

## Qué resuelve

- **Monitor en vivo**: tablero de todas las órdenes activas (instalaciones, soporte, PLEX), con filtros por técnico/actividad/estado y ubicación GPS de cada técnico.
- **Centro de Reportes**: cierre diario, pendientes generales, análisis de red (OLT/PON), diagnóstico de causas de offline, análisis cruzado — todo exportable en PDF/Excel.
- **Control de Calidad**: encuestas de satisfacción post-servicio (llamadas a clientes de INSFIBRA), auditorías de campo de Operaciones/Instalaciones/Fibra (Miguel), y un reporte de cierres INSFIBRA por rango de fechas con marcado automático de qué órdenes ya tienen llamada gestionada.
- **Expedientes**: registro y consulta de faltas/incidencias de personal (técnicos y administrativos), con clasificación automática por gravedad, resumen mensual por colaborador y generación de reportes en PDF/Word.
- **Auditoría de Vehículos**: control de gastos, telemetría y bitácora de la flota.
- **Reprogramadas / No Instalados**: seguimiento de órdenes agendadas a futuro y de cierres NOINSTALADO del día.
- **Bot de Telegram**: cualquier jefe de SAC u Operaciones puede reportar una falta desde el grupo de Telegram del equipo (con un formulario guiado por botones o en texto libre), y queda guardada automáticamente en Expedientes — para no depender de que alguien abra la app a tiempo.

## Arquitectura

```
                    ┌─────────────────────┐
                    │   API Cepheus (IT)   │   red interna de MAXCOM,
                    │  (órdenes en vivo)   │   solo alcanzable desde una PC en esa red
                    └──────────┬───────────┘
                               │ cada 15 min
                               ▼
                    ┌─────────────────────┐
                    │    sync_job.py       │   corre en una PC de MAXCOM (robot-monitor),
                    │  (robot en segundo   │   NO dentro de Streamlit
                    │       plano)         │
                    └──────────┬───────────┘
                               │ escribe
                 ┌─────────────┴─────────────┐
                 ▼                           ▼
        ┌─────────────────┐        ┌──────────────────┐
        │  Google Sheets   │◄──────►│  Google Cloud     │
        │ (fuente viva,    │  espejo │  Storage (GCS)    │
        │  Sheet1/Calidad/ │        │ (respaldo CSV,     │
        │  Expedientes/...)│        │  lectura rápida)   │
        └────────┬─────────┘        └─────────┬─────────┘
                  │                            │
                  └─────────────┬──────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │   app.py (Streamlit)     │  interfaz web principal,
                    │  login.py / tools.py /   │  desplegada en Streamlit Cloud
                    │  ccalidad.py / expedien- │
                    │  te.py / settings.py /   │
                    │  auditorv.py / ...       │
                    └─────────────────────────┘

        ┌─────────────────────────┐
        │   telegram_bot.py        │  corre en la misma PC que sync_job.py,
        │  (bot de Telegram, robot  │  escucha el grupo y guarda faltas
        │   independiente)          │  directo en Google Sheets + GCS
        └─────────────────────────┘
```

Puntos clave de este diseño:

- **`sync_job.py` y `telegram_bot.py` NO corren dentro de Streamlit.** Son procesos Python independientes que deben ejecutarse en una PC con acceso a la red interna de MAXCOM (donde vive la API de Cepheus), típicamente `C:\Maxcom`. Usan `gspread`/`google-auth` directamente en vez de `st.connection`, porque ese objeto no existe fuera de una sesión real de Streamlit.
- **Google Sheets es la fuente "viva"** (lo que la gente edita a mano si hace falta); **GCS guarda un espejo en CSV** para lecturas rápidas y como respaldo si Sheets falla o se re-despliega la app.
- **La API de Cepheus tiene un límite duro de ~2 meses** en `fechaInicio` y de 5 consultas/hora — por eso el histórico completo se acumula incrementalmente en Sheets/GCS en vez de volver a pedirlo siempre a la API.

## Módulos del sistema

| Archivo | Qué hace |
|---|---|
| `app.py` | Punto de entrada de Streamlit. Login, menú de navegación por rol, Monitor en Vivo, Centro de Reportes, Reprogramadas/No Instalados, orquesta al resto de módulos. |
| `login.py` | Autenticación contra `st.secrets["credenciales"]`, sesión persistida en cookie (30 min de inactividad). |
| `tools.py` | Caja de herramientas central: conexión con la API de Cepheus, lectura/escritura en GCS, generación de PDFs (fpdf2), clasificación de órdenes, utilidades de fecha/hora Honduras, matching difuso de nombres de personal, etc. La mayoría de los demás módulos importan de aquí. |
| `clasificador.py` | Única fuente de verdad para clasificar actividades (PLEX/SOP/Instalación/Otros) y para el "día operativo" (jornada que arranca a las 6:00 a.m.). Sin dependencias de Streamlit/pandas pesadas, para poder probarlo aislado. |
| `fechas.py` | Ayudantes de fecha sin dependencias pesadas (día operativo, parsing seguro). |
| `ccalidad.py` | Módulo de Control de Calidad: llamadas de satisfacción, auditorías de campo (Operaciones/Instalaciones/Fibra), reporte de cierres INSFIBRA por rango de fechas, histórico y reportes en PDF. |
| `expediente.py` | Módulo de Expedientes: alta de faltas/incidencias, historial filtrable, clasificación automática GRAVE/LEVE, resumen mensual por colaborador, exportación a PDF/Word, repositorio de documentos por colaborador. |
| `settings.py` | Panel de configuración (solo admin) y manual de usuario (misma fuente para pantalla y PDF descargable). |
| `auditorv.py` | Auditoría de vehículos: gastos de flota, telemetría, bitácora. |
| `tiempot.py` | Módulo de tiempos de técnicos (rendimiento/tiempos muertos). |
| `biometrico.py` | Procesamiento de reportes de biométrico/asistencia desde PDF. **No está enlazado al menú principal actualmente** — código auxiliar disponible pero no expuesto en la navegación de `app.py`. |
| `ui_components.py` | Componentes de UI reutilizables (modales de detalle de orden). |
| `sync_job.py` | Robot de sincronización: consulta Cepheus cada 15 minutos y escribe en Sheets + GCS. Corre como proceso aparte (`python sync_job.py`), no dentro de la app web. |
| `telegram_bot.py` | Bot de Telegram para reportar faltas desde el grupo del equipo (formulario guiado por botones o texto libre), guarda en Expedientes. Corre como proceso aparte. |
| `iniciar_telegram_bot.bat` / `iniciar_telegram_bot_oculto.vbs` | Lanzadores para Windows: arrancan el bot de Telegram sin ventana visible, con reinicio automático si se cae, y pueden dejarse en la carpeta de inicio de Windows para que arranquen solos. |
| `personal_tecnico.txt` / `personal_sac.txt` | Catálogos de personal (técnicos y administrativos/SAC) usados para el matching difuso de nombres en Expedientes y el bot de Telegram. |

## Roles y permisos

Los roles se definen en `st.secrets["credenciales"]` (uno por usuario) y controlan qué ve cada quien en el menú:

- **`admin`** y **`jefe`**: acceso completo — Monitor, Reportes, Calidad, Reprog/No Inst, Auditoría de Vehículos, Configuración, Expedientes.
- Resto de usuarios (rol genérico, ej. `monitoreo`): solo Monitor en Vivo y Control de Calidad.
- **`llamados`**: acceso exclusivo al módulo de Expedientes (pensado para quien solo gestiona llamadas/faltas).
- Dentro de Control de Calidad, el **nombre de usuario** (no el rol) decide la vista: `sac` ve la pestaña de llamadas + el reporte de cierres INSFIBRA restringido a INSFIBRA cerradas de los últimos 15 días; `miguel` ve la pestaña de Auditoría de Campo; el resto ve ambas.

## Requisitos

- Python 3.11 (ver `.devcontainer/devcontainer.json`)
- Dependencias en `requirements.txt` (Streamlit, pandas, gspread, google-cloud-storage, fpdf2, python-docx, plotly, etc.)
- Paquetes de sistema en `packages.txt` (`tesseract-ocr` y el paquete de idioma español, para OCR de reportes biométricos)
- Una hoja de Google Sheets y un bucket de Google Cloud Storage, con una cuenta de servicio de Google con acceso a ambos
- Para el robot de sincronización: acceso de red a la API interna de Cepheus (solo disponible dentro de la red de MAXCOM)
- Para el bot de Telegram: un bot creado con [@BotFather](https://t.me/BotFather) agregado al grupo, con el "Group Privacy" desactivado

Instalación:

```bash
pip install -r requirements.txt
# en Debian/Ubuntu, además:
sudo xargs apt install -y < packages.txt
```

## Configuración (`secrets.toml`)

**Este repositorio es público — nunca commitear un `secrets.toml` real.** La app lee toda credencial desde `st.secrets` (Streamlit) o desde `.streamlit/secrets.toml` (scripts independientes). Estructura esperada (con valores de ejemplo, no reales):

```toml
url_base_datos = "https://docs.google.com/spreadsheets/d/TU_HOJA_AQUI"

[connections.gsheets]
# Credenciales de la cuenta de servicio de Google (JSON de service account),
# con acceso tanto a la hoja de Sheets como al bucket de GCS.
type = "service_account"
project_id = "..."
private_key = "..."
client_email = "..."
# (resto de campos estándar de un service account JSON)

[credenciales.nombre_usuario]
clave = "..."
rol = "admin"   # admin | jefe | monitoreo | llamados | ...

[cepheus_api]
url = "https://..."            # endpoint interno de Cepheus (red de MAXCOM)
usuario = "..."
contrasena = "..."
usuarios_consulta = ["usuario1", "usuario2"]

[telegram]
token = "..."      # token del bot, de @BotFather
chat_id = "..."     # ID del grupo de Telegram donde se reportan faltas

# Opcionales:
catbox_userhash = "..."   # cuenta de Catbox.moe para subir evidencias fotográficas
[wati]
api_url = "..."
access_token = "..."
template_name = "..."
```

`sync_job.py` y `telegram_bot.py` leen este mismo archivo con `toml.load()` (no usan `st.secrets`, porque corren fuera de Streamlit), así que en la PC donde se ejecutan debe existir `.streamlit/secrets.toml` junto al resto del código.

## Cómo correrlo

### App principal (Streamlit)

```bash
streamlit run app.py
```

### Robot de sincronización con Cepheus

Debe correr en una PC con acceso a la red interna de MAXCOM (no funciona en Streamlit Cloud):

```bash
python sync_job.py                 # ciclo continuo, cada 15 minutos
python sync_job.py --backfill 60   # trae hasta 60 días atrás una sola vez y termina
```

### Bot de Telegram

También debe correr en una PC con acceso a Google Sheets/GCS (usa el mismo `secrets.toml`):

```bash
python telegram_bot.py
```

En Windows, para que quede corriendo en segundo plano sin una terminal abierta y se reinicie solo si se cae: copiar `iniciar_telegram_bot_oculto.vbs` a la carpeta de inicio de Windows (`shell:startup`). Ver los comentarios dentro de ese archivo y de `iniciar_telegram_bot.bat` para el detalle.

En el grupo de Telegram, cualquier jefe puede reportar una falta con `/falta` (formulario guiado por botones) o escribiendo directamente el formato de texto libre `FALTA: ...`.

## Pruebas automatizadas

```bash
python test_clasificador.py
python test_dia_operativo.py
```

Cubren la lógica de clasificación de actividades/día operativo en `clasificador.py` y `fechas.py` — los únicos módulos sin dependencias pesadas, pensados específicamente para poder probarse de forma aislada.

## Despliegue en producción

La app está desplegada en **Streamlit Cloud**, con auto-deploy desde la rama `main`. `sync_job.py` y `telegram_bot.py` corren aparte, en una PC de MAXCOM (no en Streamlit Cloud), porque necesitan estar dentro de la red interna para alcanzar la API de Cepheus.

## Dónde vive cada dato

| Dato | Google Sheets (pestaña) | Espejo en GCS |
|---|---|---|
| Órdenes de Cepheus | `Sheet1` | `historial_maestro.csv` |
| Faltas/incidencias (Expedientes) | `Expedientes` | `expedientes_maestro.csv` |
| Encuestas de satisfacción / gestión de llamadas | `Calidad` | `calidad_maestro.csv` |
| Auditorías de campo (Operaciones/Instalaciones) | `Operaciones` / `Instalaciones` | `operaciones_maestro.csv` / `instalaciones_maestro.csv` |
| Auditorías de Fibra en Campo (Miguel) | `Auditoria_Fibra` | `auditoria_fibra_maestro.csv` |
| Auditoría de vehículos | `Auditoria` / `Registro_Flota` | `registro_escaneres_flota.csv` |
| Estado FTTX/OLT | `FTTX` | `fttx_activo.csv` |

## Seguridad

- Ninguna credencial real debe vivir en el código — todo pasa por `st.secrets`/`secrets.toml`, que está fuera del control de versiones.
- Si alguna vez se expone una credencial (capturas de pantalla, commit accidental, etc.), se trata como comprometida: rotarla de inmediato (regenerar el token en @BotFather para Telegram, rotar la cuenta de servicio de Google, cambiar contraseña en Cepheus).
- `personal_tecnico.txt`/`personal_sac.txt` y el resto de archivos de catálogo no contienen credenciales, son listas de personal para hacer matching de nombres.

## Estructura del repositorio

```
app.py                Entrada principal de Streamlit
login.py               Autenticación y sesión
tools.py               Utilidades centrales (Cepheus, GCS, PDFs, fechas, matching de nombres)
clasificador.py         Clasificación de actividades / día operativo (sin dependencias pesadas)
fechas.py               Ayudantes de fecha (sin dependencias pesadas)
ccalidad.py             Módulo de Control de Calidad
expediente.py           Módulo de Expedientes (faltas/incidencias)
settings.py             Configuración y manual de usuario
auditorv.py             Auditoría de vehículos
tiempot.py               Tiempos de técnicos
biometrico.py            Procesamiento de biométrico (no enlazado al menú actualmente)
ui_components.py         Componentes de UI reutilizables
sync_job.py              Robot de sincronización con Cepheus (proceso aparte)
telegram_bot.py          Bot de Telegram para reportar faltas (proceso aparte)
iniciar_telegram_bot.*   Lanzadores del bot para Windows
personal_tecnico.txt     Catálogo de técnicos
personal_sac.txt         Catálogo de personal administrativo/SAC
test_clasificador.py     Pruebas de clasificador.py
test_dia_operativo.py    Pruebas de fechas.py
requirements.txt         Dependencias Python
packages.txt             Dependencias de sistema (Tesseract OCR)
.streamlit/config.toml   Tema y configuración de servidor de Streamlit
.devcontainer/           Configuración de GitHub Codespaces
```
