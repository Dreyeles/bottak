"""
=============================================================================
BOT DE TELEGRAM PARA ROL CON IA MULTI-API (FAILOVER)
=============================================================================
Permite jugar partidas de rol interactivas a través de Telegram con personajes
de IA intercambiables, creación de personajes personalizados con contexto
y sistema de respaldo automático entre Groq y OpenRouter.
=============================================================================
"""

import os
import sys
import re
import json
import time
import warnings
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# Forzar flush de salida para ver logs de inmediato
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore", category=UserWarning, module="telegram")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Servidor web ultraligero para que plataformas en la nube (como Render) y monitores (como UptimeRobot) sepan que el bot está vivo."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot de Rol Telegram activo y funcionando.")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()

    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # Silenciar logs del servidor web para no ensuciar la consola


def iniciar_servidor_web_salud():
    """Inicia el servidor web solo si la plataforma en la nube asigna una variable PORT."""
    puerto_env = os.getenv("PORT")
    if puerto_env:
        try:
            puerto = int(puerto_env)
            servidor = HTTPServer(("0.0.0.0", puerto), HealthCheckHandler)
            print(f"✔ Servidor de salud web iniciado en el puerto {puerto}")
            servidor.serve_forever()
        except Exception as e:
            print(f"Aviso al iniciar servidor web de salud: {e}")
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv

from openai import OpenAI, RateLimitError, APIConnectionError, APIError, AuthenticationError, NotFoundError

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# Cargar variables de entorno
DIRECTORIO_ACTUAL = os.path.dirname(os.path.abspath(__file__))
RUTA_ENV = os.path.join(DIRECTORIO_ACTUAL, ".env")
load_dotenv(RUTA_ENV)

CARPETA_PERSONAJES = os.path.join(DIRECTORIO_ACTUAL, "personajes")
CARPETA_HISTORIALES = os.path.join(DIRECTORIO_ACTUAL, "historiales")
os.makedirs(CARPETA_PERSONAJES, exist_ok=True)
os.makedirs(CARPETA_HISTORIALES, exist_ok=True)

MAX_MENSAJES_CONTEXTO = 24

# Estados para la conversación interactiva de crear personaje
ESTADO_NOMBRE, ESTADO_TITULO, ESTADO_CONTEXTO, ESTADO_SALUDO = range(4)

# Diccionario en memoria para las sesiones activas por chat_id
sesiones_usuarios = {}
ARCHIVO_SESIONES = os.path.join(CARPETA_HISTORIALES, "sesiones_activas.json")


def guardar_sesiones_disco():
    """Persiste las sesiones activas en disco para sobrevivir a reinicios del servidor."""
    try:
        datos = {}
        for c_id, s in sesiones_usuarios.items():
            datos[str(c_id)] = {
                "personaje_archivo": s["personaje"].get("_archivo", "ada_liz.json"),
                "nombre_jugador": s.get("nombre_jugador", "Drey"),
                "historial": s.get("historial", [])
            }
        with open(ARCHIVO_SESIONES, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Aviso guardando sesiones en disco: {e}")


def cargar_sesiones_disco():
    """Restaura las sesiones activas desde el disco."""
    global sesiones_usuarios
    if not os.path.exists(ARCHIVO_SESIONES):
        return
    try:
        with open(ARCHIVO_SESIONES, "r", encoding="utf-8") as f:
            datos = json.load(f)
        for c_id_str, s_data in datos.items():
            try:
                c_id = int(c_id_str)
                archivo_p = s_data.get("personaje_archivo", "ada_liz.json")
                p = cargar_personaje_completo(archivo_p)
                if p:
                    sesiones_usuarios[c_id] = {
                        "personaje": p,
                        "nombre_jugador": s_data.get("nombre_jugador", "Drey"),
                        "historial": s_data.get("historial", [])
                    }
            except Exception:
                pass
        print(f"✔ {len(sesiones_usuarios)} sesión(es) restaurada(s) desde el disco.")
    except Exception as e:
        print(f"Aviso restaurando sesiones desde disco: {e}")


def inicializar_proveedores():
    """Configura los proveedores de IA en orden de prioridad con soporte multi-cuenta."""
    proveedores = []
    groq_keys = [
        k.strip() for k in [
            os.getenv("GROQ_API_KEY", ""),
            os.getenv("GROQ_API_KEY_2", "")
        ] if k.strip()
    ]
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    venice_key = os.getenv("VENICE_API_KEY", "").strip()

    # 1. Groq Cloud (Ultra rápido - Soporta múltiples cuentas para doble cuota)
    for idx, g_key in enumerate(groq_keys, start=1):
        sufijo = f" (Cuenta {idx})" if len(groq_keys) > 1 else ""
        cliente_groq = OpenAI(api_key=g_key, base_url="https://api.groq.com/openai/v1")
        proveedores.append({
            "nombre": f"Groq{sufijo} (GPT OSS 120B)",
            "cliente": cliente_groq,
            "modelo": "openai/gpt-oss-120b",
            "temperatura": 0.8
        })
        proveedores.append({
            "nombre": f"Groq{sufijo} (GPT OSS 20B)",
            "cliente": cliente_groq,
            "modelo": "openai/gpt-oss-20b",
            "temperatura": 0.8
        })
        proveedores.append({
            "nombre": f"Groq{sufijo} (Qwen 27B)",
            "cliente": cliente_groq,
            "modelo": "qwen/qwen3.8-27b",
            "temperatura": 0.8
        })

    # 2. OpenRouter (Modelos gratuitos)
    if openrouter_key:
        cliente_openrouter = OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "https://github.com/bot-rol", "X-Title": "Bot Rol Telegram"}
        )
        proveedores.append({
            "nombre": "OpenRouter (Nemotron 550B)",
            "cliente": cliente_openrouter,
            "modelo": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "temperatura": 0.8
        })
        proveedores.append({
            "nombre": "OpenRouter (Nemotron Lightning)",
            "cliente": cliente_openrouter,
            "modelo": "nvidia/nemotron-3.5-lightning:free",
            "temperatura": 0.8
        })

    # 3. Venice AI (Especializado en rol sin censura)
    if venice_key:
        cliente_venice = OpenAI(api_key=venice_key, base_url="https://api.venice.ai/api/v1")
        proveedores.append({
            "nombre": "Venice AI (Role Play Uncensored)",
            "cliente": cliente_venice,
            "modelo": "venice-uncensored-role-play",
            "temperatura": 0.8
        })
        proveedores.append({
            "nombre": "Venice AI (Uncensored 1.2)",
            "cliente": cliente_venice,
            "modelo": "venice-uncensored-1-2",
            "temperatura": 0.8
        })

    return proveedores


def cargar_personaje_completo(archivo):
    """Carga un personaje desde su archivo JSON y fusiona su archivo .md complementario si existe."""
    ruta = os.path.join(CARPETA_PERSONAJES, archivo)
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        datos["_archivo"] = archivo
        if isinstance(datos.get("system_prompt"), list):
            datos["system_prompt"] = "\n".join(datos["system_prompt"])
        if isinstance(datos.get("saludo_inicial"), list):
            datos["saludo_inicial"] = "\n".join(datos["saludo_inicial"])

        # Cargar archivo de contexto en Markdown complementario si existe
        ruta_ctx_md = os.path.join(CARPETA_PERSONAJES, archivo.replace(".json", "_contexto.md"))
        if os.path.exists(ruta_ctx_md):
            try:
                with open(ruta_ctx_md, "r", encoding="utf-8") as f_ctx:
                    texto_ctx = f_ctx.read().strip()
                    if texto_ctx:
                        # Limitar a máximo 15,000 caracteres para no exceder los límites de tokens por minuto (TPM)
                        if len(texto_ctx) > 15000:
                            texto_ctx = texto_ctx[:15000] + "\n\n... (recuerdos adicionales guardados en archivo)"
                        datos["system_prompt"] += f"\n\n=== MEMORIAS Y ANÉCDOTAS HISTÓRICAS DE WHATSAPP ===\n{texto_ctx}"
            except Exception as e_ctx:
                print(f"Aviso leyendo contexto .md de {archivo}: {e_ctx}")

        return datos
    except Exception as e:
        print(f"Error cargando {archivo}: {e}")
        return None


def cargar_personajes():
    """Carga todos los personajes disponibles."""
    personajes = []
    if not os.path.exists(CARPETA_PERSONAJES):
        return personajes

    for archivo in sorted(os.listdir(CARPETA_PERSONAJES)):
        if archivo.endswith(".json"):
            p = cargar_personaje_completo(archivo)
            if p:
                personajes.append(p)
    return personajes


def es_respuesta_censurada(texto):
    """Detecta de forma exhaustiva si un modelo emitió una respuesta enlatada de censura o rechazo."""
    if not texto:
        return False
    # Normalizar texto (minúsculas, sin apóstrofes ni signos)
    t = texto.lower().replace("'", "").replace("’", "").replace("`", "").strip()

    patrones = [
        "cant help with that",
        "cannot help with that",
        "cant assist with that",
        "cannot assist with that",
        "cant fulfill this",
        "cannot fulfill this",
        "sorry, i cant",
        "sorry i cant",
        "sorry, i cannot",
        "sorry i cannot",
        "im sorry, but i cant",
        "im sorry but i cant",
        "i am sorry, but i cannot",
        "i am unable to help",
        "im unable to help",
        "unable to assist with that",
        "as an ai",
        "as a language model",
        "safety guidelines",
        "content policy",
        "against my programming",
        "no puedo ayudarte con eso",
        "no puedo ayudarte con esta",
        "no puedo cumplir con",
        "no puedo asistir",
        "como modelo de lenguaje",
        "como inteligencia artificial",
        "como una ia",
        "lo siento, pero no puedo",
        "lo siento pero no puedo",
        "no me siento comoda",
        "no estoy programada para",
        "no tengo permitido"
    ]
    return any(p in t for p in patrones)


def limpiar_texto_respuesta(texto):
    """Limpia etiquetas think, reflexiones meta en inglés y monólogos internos entre paréntesis."""
    if not texto:
        return ""
    # 1. Eliminar etiquetas <think>...</think>
    t = re.sub(r"<think>.*?</think>", "", texto, flags=re.DOTALL)
    # 2. Eliminar pensamientos en inglés entre paréntesis (monólogo interno o deliberación de reglas)
    t = re.sub(r"\([^)]*?(?:emoticon|emoji|graphic|rule|allow|can\'t|cannot|let\'s|we must|think|actually)[^)]*?\)", "\n", t, flags=re.IGNORECASE | re.DOTALL)
    # 3. Eliminar bloques de reflexión que empiecen con conectores típicos en inglés
    t = re.sub(r"\((?:But|Wait|Actually|Let\'s|Note|I should|Can\'t|We must|Thinking)[^)]*?\)", "\n", t, flags=re.IGNORECASE | re.DOTALL)

    t = t.strip()
    lineas = [l.strip() for l in t.splitlines() if l.strip()]
    if len(lineas) >= 2 and len(lineas[0]) > 8 and len(lineas[-1]) > 8:
        if lineas[0][:12].lower() == lineas[-1][:12].lower():
            t = lineas[-1]

    return t.strip()


def _generar_respuesta_sync(proveedores, historial):
    """Llamada síncrona a las APIs con failover (ejecutada en hilo secundario)."""
    if len(historial) > MAX_MENSAJES_CONTEXTO:
        mensajes_para_enviar = [historial[0]] + historial[-(MAX_MENSAJES_CONTEXTO - 1):]
    else:
        mensajes_para_enviar = historial

    for prov in proveedores:
        try:
            res = prov["cliente"].chat.completions.create(
                model=prov["modelo"],
                messages=mensajes_para_enviar,
                temperature=prov.get("temperatura", 0.8),
                stream=False,
                timeout=15.0
            )
            if res.choices and res.choices[0].message.content:
                texto_resp = res.choices[0].message.content.strip()
                # Detectar y filtrar negativas o censura de IA para activar failover
                if es_respuesta_censurada(texto_resp):
                    print(f"Aviso: {prov['nombre']} emitió negativa de censura ('{texto_resp[:50]}...'). Saltando al siguiente proveedor...")
                    continue

                texto_limpio = limpiar_texto_respuesta(texto_resp)
                if texto_limpio:
                    return texto_limpio, prov["nombre"]
        except RateLimitError as e:
            print(f"Aviso: {prov['nombre']} con límite de tasa ({e}). Reintentando tras 1.5s...")
            time.sleep(1.5)
            try:
                res = prov["cliente"].chat.completions.create(
                    model=prov["modelo"],
                    messages=mensajes_para_enviar,
                    temperature=prov.get("temperatura", 0.8),
                    stream=False,
                    timeout=15.0
                )
                if res.choices and res.choices[0].message.content:
                    texto_resp = res.choices[0].message.content.strip()
                    if not es_respuesta_censurada(texto_resp):
                        texto_limpio = limpiar_texto_respuesta(texto_resp)
                        if texto_limpio:
                            return texto_limpio, prov["nombre"]
            except Exception:
                pass
            continue
        except Exception as e:
            print(f"Aviso: {prov['nombre']} falló: {e}. Probando siguiente proveedor...")
            continue

    return None, None


async def generar_respuesta_ia(proveedores, historial):
    """Wrapper asíncrono para no bloquear el bot de Telegram."""
    return await asyncio.to_thread(_generar_respuesta_sync, proveedores, historial)


async def enviar_mensaje_seguro(bot, chat_id, texto):
    """Intenta enviar el mensaje con formato Markdown; si falla por sintaxis, lo envía en texto plano."""
    try:
        await bot.send_message(chat_id=chat_id, text=texto, parse_mode=constants.ParseMode.MARKDOWN)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=texto)


def teclado_personajes():
    """Genera los botones con los personajes disponibles y el botón para crear uno nuevo."""
    personajes = cargar_personajes()
    botones = []
    for p in personajes:
        archivo = p.get("_archivo", "")
        nombre = p.get("nombre", "Personaje")
        genero = p.get("genero", "")
        genero_corto = genero.split("/")[0].strip() if "/" in genero else genero
        texto_boton = f"🎭 {nombre} ({genero_corto})"
        botones.append([InlineKeyboardButton(texto_boton, callback_data=f"sel_{archivo}")])

    # Botón destacado para crear personaje con contexto propio
    botones.append([InlineKeyboardButton("✨ ➕ Crear nuevo personaje con contexto", callback_data="crear_nuevo_personaje")])
    return InlineKeyboardMarkup(botones)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start: Da la bienvenida y muestra selector de personajes."""
    user = update.effective_user
    nombre_jugador = user.first_name or "Aventurero"

    texto = (
        f"👋 ¡Hola, *{nombre_jugador}*!\n\n"
        "Bienvenido al **Bot de Rol con Inteligencia Artificial**.\n"
        "Aquí puedes jugar partidas de rol conversacionales con personajes vivos y memorias persistentes.\n\n"
        "🎭 *Elige con quién deseas jugar o crea uno nuevo a tu gusto:*"
    )
    await update.message.reply_text(texto, parse_mode=constants.ParseMode.MARKDOWN, reply_markup=teclado_personajes())


async def cmd_personajes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /personajes: Muestra la lista de personajes para cambiar o crear."""
    await update.message.reply_text(
        "🎭 *Selecciona un personaje o crea uno nuevo:*",
        parse_mode=constants.ParseMode.MARKDOWN,
        reply_markup=teclado_personajes()
    )


# =============================================================================
# FLUJO INTERACTIVO: CREAR PERSONAJE CON CONTEXTO
# =============================================================================

async def iniciar_creacion_personaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 1: Inicia el asistente interactivo pidiendo el nombre."""
    mensaje = (
        "✨ **CREADOR DE PERSONAJES PERSONALIZADOS**\n"
        "───────────────────────────────\n\n"
        "1️⃣ **¿Cómo se llama tu nuevo personaje?**\n\n"
        "_(Escribe el nombre aquí en el chat, o envía /cancelar para salir)_"
    )
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(mensaje, parse_mode=constants.ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(mensaje, parse_mode=constants.ParseMode.MARKDOWN)

    return ESTADO_NOMBRE


async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 2: Recibe el nombre y pide el título o rol."""
    nombre = update.message.text.strip()
    if not nombre:
        await update.message.reply_text("Por favor, escribe un nombre válido:")
        return ESTADO_NOMBRE

    context.user_data["nuevo_nombre"] = nombre

    await update.message.reply_text(
        f"Excelente, el personaje se llamará *{nombre}*.\n\n"
        "2️⃣ **¿Cuál es su título, profesión o arquetipo?**\n"
        "_(Ejemplos: Hechicera oscura, Cazarrecompensas espacial, Detective cínico, Tabernero enano)_",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ESTADO_TITULO


async def recibir_titulo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 3: Recibe el título y pide el contexto/personalidad."""
    titulo = update.message.text.strip()
    context.user_data["nuevo_titulo"] = titulo or "Aventurero"

    nombre = context.user_data.get("nuevo_nombre", "Personaje")

    await update.message.reply_text(
        f"Perfecto: *{nombre}*, _{titulo}_.\n\n"
        "3️⃣ **Cuéntame su contexto, trasfondo y personalidad:**\n\n"
        "Puedes incluir todo lo que quieras:\n"
        "• Su pasado o secretos.\n"
        "• Cómo habla (formal, sarcástico, tosco, poético).\n"
        "• Su actitud hacia ti (hostil, servicial, desconfiado).\n"
        "• El mundo donde se encuentran (cyberpunk, medieval, apocalipsis).\n\n"
        "_(¡Sé tan detallado como gustes! Todo esto se grabará en la memoria del bot)_",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ESTADO_CONTEXTO


async def recibir_contexto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 4: Recibe el contexto y pide el saludo inicial."""
    contexto = update.message.text.strip()
    context.user_data["nuevo_contexto"] = contexto

    nombre = context.user_data.get("nuevo_nombre", "Personaje")

    await update.message.reply_text(
        "4️⃣ **¿Cuál será su saludo o escena inicial?**\n\n"
        "Describe cómo empieza la partida usando asteriscos para las acciones. Ejemplo:\n"
        f"`*{nombre} te mira de reojo mientras recarga su arma.* —Llegas justo a tiempo.`\n\n"
        "👉 _(O simplemente escribe **`auto`** para que la IA genere un saludo inicial épico automáticamente)_",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ESTADO_SALUDO


async def recibir_saludo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paso 5: Guarda el personaje en personajes/*.json e inicia la partida inmediatamente."""
    saludo_input = update.message.text.strip()
    nombre = context.user_data.get("nuevo_nombre", "Personaje")
    titulo = context.user_data.get("nuevo_titulo", "Aventurero")
    contexto = context.user_data.get("nuevo_contexto", "Personaje de rol.")

    if saludo_input.lower() in ["auto", "automático", "automatico"]:
        saludo = f"*{nombre} se detiene al notar tu presencia, evaluándote de arriba abajo con mirada atenta.* —Dime a qué has venido."
    else:
        saludo = saludo_input

    # Crear system prompt completo
    system_prompt = (
        f"Eres {nombre}, {titulo}.\n"
        f"Contexto, personalidad y trasfondo: {contexto}.\n"
        "Mantén siempre el rol al 100%. Describe tus acciones, lenguaje corporal y entorno entre asteriscos (*así*), "
        "y tus palabras habladas con guiones largos o comillas directas. Reacciona dinámicamente al jugador."
    )

    # Guardar en archivo JSON permanente
    slug = "".join(c for c in nombre.lower() if c.isalnum() or c == '_').strip() or "personaje"
    ruta_p = os.path.join(CARPETA_PERSONAJES, f"{slug}.json")
    contador = 1
    while os.path.exists(ruta_p):
        ruta_p = os.path.join(CARPETA_PERSONAJES, f"{slug}_{contador}.json")
        contador += 1

    datos_nuevo = {
        "nombre": nombre,
        "titulo": titulo,
        "genero": "Personalizado",
        "saludo_inicial": saludo,
        "system_prompt": system_prompt,
        "_archivo": os.path.basename(ruta_p)
    }

    try:
        with open(ruta_p, "w", encoding="utf-8") as f:
            json.dump(datos_nuevo, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error al guardar personaje en disco: {e}")

    # Iniciar la sesión de juego inmediatamente para este usuario
    chat_id = update.effective_chat.id
    user = update.effective_user
    nombre_jugador = user.first_name or "Aventurero"

    prompt_con_jugador = (
        f"{system_prompt}\n"
        f"El usuario interactúa contigo a través de Telegram bajo el nombre o personaje de '{nombre_jugador}'."
    )

    sesiones_usuarios[chat_id] = {
        "personaje": datos_nuevo,
        "nombre_jugador": nombre_jugador,
        "historial": [
            {"role": "system", "content": prompt_con_jugador},
            {"role": "assistant", "content": saludo}
        ]
    }

    mensaje_exito = (
        f"🎉 **¡PERSONAJE CREADO Y GUARDADO!**\n"
        f"*{nombre}* ahora forma parte de tu catálogo permanente.\n"
        f"────────────────────────\n\n"
        f"⚔️ **Iniciando escena con {nombre.upper()} ({titulo}):**\n\n"
        f"{saludo}\n\n"
        f"💬 *Escribe tu mensaje para responderle.*"
    )
    await update.message.reply_text(mensaje_exito, parse_mode=constants.ParseMode.MARKDOWN)

    # Limpiar datos temporales
    context.user_data.clear()
    return ConversationHandler.END


async def cancelar_creacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela la creación del personaje."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Creación de personaje cancelada. Usa /personajes cuando desees elegir uno existente.",
        parse_mode=constants.ParseMode.MARKDOWN
    )
    return ConversationHandler.END


# =============================================================================
# MANEJO DE SELECCIÓN Y PARTIDA
# =============================================================================

async def callback_personaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja el clic en los botones de selección de personaje predefinido."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if not data.startswith("sel_"):
        return

    archivo = data.replace("sel_", "")
    datos_p = cargar_personaje_completo(archivo)

    if not datos_p:
        await query.edit_message_text("❌ Personaje no encontrado.")
        return

    chat_id = update.effective_chat.id
    user = update.effective_user
    nombre_jugador = user.first_name or "Aventurero"

    nombre = datos_p.get("nombre", "Personaje")
    titulo = datos_p.get("titulo", "")
    genero = datos_p.get("genero", "")
    saludo = datos_p.get("saludo_inicial", f"*{nombre} te observa en silencio.*")
    prompt_base = datos_p.get("system_prompt", f"Eres {nombre}. Mantén siempre el rol.")

    prompt_completo = (
        f"{prompt_base}\n"
        f"El usuario interactúa contigo a través de Telegram bajo el nombre o personaje de '{nombre_jugador}'."
    )

    # Iniciar la sesión del usuario
    sesiones_usuarios[chat_id] = {
        "personaje": datos_p,
        "nombre_jugador": nombre_jugador,
        "historial": [
            {"role": "system", "content": prompt_completo},
            {"role": "assistant", "content": saludo}
        ]
    }
    guardar_sesiones_disco()

    mensaje_inicio = (
        f"⚔️ *Escenario iniciado con: {nombre.upper()}*\n"
        f"_{titulo} ({genero})_\n"
        f"────────────────────────\n\n"
        f"{saludo}\n\n"
        f"💡 *Escribe tu mensaje o acción para responder.* (Usa /ayuda para ver comandos)"
    )

    await query.edit_message_text(mensaje_inicio, parse_mode=constants.ParseMode.MARKDOWN)


async def cmd_limpiar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /limpiar: Reinicia la partida actual desde el saludo inicial."""
    chat_id = update.effective_chat.id
    if chat_id not in sesiones_usuarios:
        await update.message.reply_text("ℹ️ No tienes ninguna partida activa. Usa /personajes para elegir uno.")
        return

    sesion = sesiones_usuarios[chat_id]
    archivo = sesion["personaje"].get("_archivo", "")
    if archivo:
        datos_recargados = cargar_personaje_completo(archivo)
        if datos_recargados:
            sesion["personaje"] = datos_recargados

    datos_p = sesion["personaje"]
    nombre = datos_p.get("nombre", "Personaje")
    saludo = datos_p.get("saludo_inicial", f"*{nombre} te observa en silencio.*")
    nombre_jugador = sesion.get("nombre_jugador", "Aventurero")
    prompt_base = datos_p.get("system_prompt", f"Eres {nombre}. Mantén siempre el rol.")

    system_prompt = (
        f"{prompt_base}\n"
        f"El usuario interactúa contigo a través de Telegram bajo el nombre o personaje de '{nombre_jugador}'."
    )

    sesion["historial"] = [
        {"role": "system", "content": system_prompt},
        {"role": "assistant", "content": saludo}
    ]
    guardar_sesiones_disco()

    await update.message.reply_text(
        f"🔄 *Partida reiniciada con {nombre}*\n\n{saludo}",
        parse_mode=constants.ParseMode.MARKDOWN
    )


async def cmd_guardar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /guardar: Guarda la partida y envía el archivo .txt directamente a Telegram."""
    chat_id = update.effective_chat.id
    if chat_id not in sesiones_usuarios or len(sesiones_usuarios[chat_id]["historial"]) <= 1:
        await update.message.reply_text("ℹ️ No hay suficiente conversación en esta partida para guardar.")
        return

    sesion = sesiones_usuarios[chat_id]
    nombre_p = sesion["personaje"].get("nombre", "Personaje")
    nombre_j = sesion["nombre_jugador"]
    historial = sesion["historial"]

    # Crear contenido en memoria
    buffer = BytesIO()
    lineas = [
        f"=== SESIÓN DE ROL CON {nombre_p.upper()} (TELEGRAM) ===\n",
        f"Jugador: {nombre_j}\n",
        f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
    ]
    for msg in historial:
        rol = msg.get("role", "")
        contenido = msg.get("content", "")
        if rol == "system":
            continue
        etiqueta = nombre_j if rol == "user" else nombre_p
        lineas.append(f"[{etiqueta.upper()}]:\n{contenido}\n\n")

    buffer.write("".join(lineas).encode("utf-8"))
    buffer.seek(0)

    nombre_archivo = f"rol_{nombre_p.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    await update.message.reply_document(
        document=buffer,
        filename=nombre_archivo,
        caption=f"📜 ¡Aquí tienes el historial completo de tu partida con *{nombre_p}*!",
        parse_mode=constants.ParseMode.MARKDOWN
    )


async def cmd_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda: Muestra los comandos disponibles."""
    texto = (
        "📖 *Comandos del Bot de Rol:*\n\n"
        "• /personajes - Ver catálogo y crear personajes nuevos.\n"
        "• /crear - Iniciar el asistente para crear un personaje con contexto.\n"
        "• /limpiar - Reiniciar la escena actual desde cero.\n"
        "• /guardar - Descargar la transcripción de la partida en archivo .txt.\n"
        "• /ayuda - Muestra esta ayuda.\n\n"
        "💡 *Consejo de rol:* Usa asteriscos para describir tus acciones (ej: `*desenvaino mi espada* ¿quién eres?`)."
    )
    await update.message.reply_text(texto, parse_mode=constants.ParseMode.MARKDOWN)


async def manejar_mensaje_usuario(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja las entradas de texto del usuario durante el juego."""
    chat_id = update.effective_chat.id
    texto_usuario = update.message.text.strip()

    if not texto_usuario:
        return

    # Si no tiene personaje en memoria, intentar cargar desde disco
    if chat_id not in sesiones_usuarios:
        cargar_sesiones_disco()

    # Si aún así no tiene sesión activa, auto-iniciar con Ada Liz para no interrumpir al usuario
    if chat_id not in sesiones_usuarios:
        p_ada = cargar_personaje_completo("ada_liz.json")
        if p_ada:
            nombre_jugador = update.effective_user.first_name or "Drey"
            prompt_completo = (
                f"{p_ada['system_prompt']}\n"
                f"El usuario interactúa contigo a través de WhatsApp/Telegram bajo el nombre de '{nombre_jugador}'."
            )
            sesiones_usuarios[chat_id] = {
                "personaje": p_ada,
                "nombre_jugador": nombre_jugador,
                "historial": [
                    {"role": "system", "content": prompt_completo},
                    {"role": "assistant", "content": p_ada.get("saludo_inicial", "Holo :3")}
                ]
            }
            guardar_sesiones_disco()
        else:
            await update.message.reply_text(
                "👋 Primero debes elegir o crear un personaje con el que quieras jugar:",
                reply_markup=teclado_personajes()
            )
            return

    sesion = sesiones_usuarios[chat_id]
    nombre_p = sesion["personaje"].get("nombre", "Personaje")
    proveedores = context.bot_data.get("proveedores", [])

    if not proveedores:
        await update.message.reply_text("⚠️ No hay proveedores de IA configurados en el servidor.")
        return

    # Agregar mensaje del usuario al historial
    sesion["historial"].append({"role": "user", "content": texto_usuario})

    # Tarea en segundo plano para mantener la acción 'escribiendo...' en Telegram mientras la IA genera
    async def mantener_indicador_escribiendo():
        while True:
            try:
                await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
                await asyncio.sleep(4)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    tarea_escribiendo = asyncio.create_task(mantener_indicador_escribiendo())
    try:
        # Generar respuesta con failover
        respuesta, prov_usado = await generar_respuesta_ia(proveedores, sesion["historial"])
    finally:
        tarea_escribiendo.cancel()

    if respuesta:
        sesion["historial"].append({"role": "assistant", "content": respuesta})
        guardar_sesiones_disco()
        await enviar_mensaje_seguro(context.bot, chat_id, respuesta)
    else:
        # Revertir el último mensaje si todas las APIs fallaron
        sesion["historial"].pop()
        await update.message.reply_text(
            "⚠️ Lo siento, los servicios de IA están temporalmente saturados. Intenta enviar tu mensaje de nuevo en unos segundos."
        )


def main():
    token_telegram = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

    if not token_telegram:
        print("\n❌ Error: No se encontró TELEGRAM_BOT_TOKEN en el archivo .env")
        print("Obtén tu token hablando con @BotFather en Telegram y pégalo en el archivo .env")
        return

    proveedores = inicializar_proveedores()
    if not proveedores:
        print("\n❌ Error: No se encontraron claves de IA (Groq u OpenRouter) en el archivo .env")
        return

    print("=" * 60)
    print("🚀 INICIANDO BOT DE TELEGRAM (ROL MULTI-API)")
    print("=" * 60)
    print(f"✔ Proveedores de IA activos: {len(proveedores)}")
    for p in proveedores:
        print(f"  - {p['nombre']} ({p['modelo']})")

    # Iniciar servidor web de salud en segundo plano si estamos en la nube (Render / Heroku / Koyeb)
    if os.getenv("PORT"):
        hilo_web = threading.Thread(target=iniciar_servidor_web_salud, daemon=True)
        hilo_web.start()

    # Construir la aplicación de Telegram
    app = ApplicationBuilder().token(token_telegram).build()

    # Guardar proveedores en bot_data para acceso global
    app.bot_data["proveedores"] = proveedores

    # Conversación interactiva para crear personajes con contexto
    conv_crear_personaje = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(iniciar_creacion_personaje, pattern="^crear_nuevo_personaje$"),
            CommandHandler("crear", iniciar_creacion_personaje)
        ],
        states={
            ESTADO_NOMBRE: [MessageHandler(filters.TEXT & (~filters.COMMAND), recibir_nombre)],
            ESTADO_TITULO: [MessageHandler(filters.TEXT & (~filters.COMMAND), recibir_titulo)],
            ESTADO_CONTEXTO: [MessageHandler(filters.TEXT & (~filters.COMMAND), recibir_contexto)],
            ESTADO_SALUDO: [MessageHandler(filters.TEXT & (~filters.COMMAND), recibir_saludo)]
        },
        fallbacks=[CommandHandler("cancelar", cancelar_creacion)],
        per_chat=True,
        per_user=True,
        per_message=False
    )

    # Handlers
    app.add_handler(conv_crear_personaje)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("personajes", cmd_personajes))
    app.add_handler(CommandHandler("limpiar", cmd_limpiar))
    app.add_handler(CommandHandler("guardar", cmd_guardar))
    app.add_handler(CommandHandler("ayuda", cmd_ayuda))
    app.add_handler(CallbackQueryHandler(callback_personaje))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), manejar_mensaje_usuario))

    cargar_sesiones_disco()

    print("\n✔ Bot conectado a Telegram con éxito.")
    print("👉 Abre Telegram, busca tu bot y envía /start para comenzar a jugar.\n")
    print("Presiona Ctrl + C en esta terminal para detener el bot.")

    app.run_polling()


if __name__ == "__main__":
    main()
