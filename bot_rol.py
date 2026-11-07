"""
=============================================================================
BOT DE ROL MULTI-API CON SISTEMA DE RESPALDO (FAILOVER)
=============================================================================
Este bot permite chatear y jugar rol con personajes de IA usando múltiples
APIs simultáneas (Groq, OpenRouter, Venice AI). Si una API alcanza su límite
gratuito o falla, el bot salta automáticamente a la siguiente sin interrumpir
la conversación.
=============================================================================
"""

import os
import sys
import json
import time
from datetime import datetime
from dotenv import load_dotenv
import colorama
from colorama import Fore, Back, Style
from openai import OpenAI, RateLimitError, APIConnectionError, APIError, AuthenticationError, NotFoundError

# Inicializar colores en terminal (compatible con Windows y Linux)
colorama.init(autoreset=True)

# Cargar variables de entorno desde .env
DIRECTORIO_ACTUAL = os.path.dirname(os.path.abspath(__file__))
RUTA_ENV = os.path.join(DIRECTORIO_ACTUAL, ".env")
load_dotenv(RUTA_ENV)

CARPETA_PERSONAJES = os.path.join(DIRECTORIO_ACTUAL, "personajes")
CARPETA_HISTORIALES = os.path.join(DIRECTORIO_ACTUAL, "historiales")
os.makedirs(CARPETA_PERSONAJES, exist_ok=True)
os.makedirs(CARPETA_HISTORIALES, exist_ok=True)

# Límite máximo de mensajes recientes que se envían a la API para no exceder cuotas de tokens (TPM)
MAX_MENSAJES_CONTEXTO = 24


class FormateadorRolStream:
    """
    Colorea el texto generado en tiempo real durante el streaming:
    - Acciones entre *asteriscos*: en color Cyan tenue (inmersivo).
    - Diálogos y texto hablado: en color Blanco brillante.
    """
    def __init__(self):
        self.en_accion = False
        sys.stdout.write(Fore.WHITE)
        sys.stdout.flush()

    def procesar(self, texto):
        for char in texto:
            if char == '*':
                if self.en_accion:
                    # Fin de la acción descriptiva
                    sys.stdout.write(char)
                    sys.stdout.write(Fore.WHITE + Style.NORMAL)
                    self.en_accion = False
                else:
                    # Comienzo de la acción descriptiva
                    sys.stdout.write(Fore.CYAN + Style.DIM)
                    sys.stdout.write(char)
                    self.en_accion = True
            else:
                sys.stdout.write(char)
        sys.stdout.flush()

    def finalizar(self):
        if self.en_accion:
            self.en_accion = False
        sys.stdout.write(Style.RESET_ALL)
        sys.stdout.flush()


def inicializar_proveedores():
    """
    Configura y devuelve la lista de proveedores disponibles en orden de prioridad.
    """
    proveedores = []

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    venice_key = os.getenv("VENICE_API_KEY", "").strip()

    # 1. Groq Cloud (Ultra rápido y gratuito)
    if groq_key:
        proveedores.append({
            "nombre": "Groq Cloud (GPT OSS 120B)",
            "cliente": OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1"),
            "modelo": "openai/gpt-oss-120b",
            "temperatura": 0.8
        })
        proveedores.append({
            "nombre": "Groq Cloud (Qwen 27B Respaldo)",
            "cliente": OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1"),
            "modelo": "qwen/qwen3.8-27b",
            "temperatura": 0.8
        })

    # 2. OpenRouter (Modelos gratuitos de respaldo)
    if openrouter_key:
        cliente_openrouter = OpenAI(
            api_key=openrouter_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={"HTTP-Referer": "https://github.com/bot-rol", "X-Title": "Bot Rol IA"}
        )
        proveedores.append({
            "nombre": "OpenRouter (Nemotron 550B Gratis)",
            "cliente": cliente_openrouter,
            "modelo": "nvidia/nemotron-3-ultra-550b-a55b:free",
            "temperatura": 0.8
        })
        proveedores.append({
            "nombre": "OpenRouter (Nemotron Lightning Gratis)",
            "cliente": cliente_openrouter,
            "modelo": "nvidia/nemotron-3.5-lightning:free",
            "temperatura": 0.8
        })

    # 3. Venice AI (Privacidad / Sin censura)
    if venice_key:
        proveedores.append({
            "nombre": "Venice AI",
            "cliente": OpenAI(api_key=venice_key, base_url="https://api.venice.ai/api/v1"),
            "modelo": "llama-3.3-70b",
            "temperatura": 0.8
        })

    return proveedores


def listar_personajes():
    """Lee las tarjetas de personaje en formato JSON dentro de personajes/."""
    personajes = []
    if not os.path.exists(CARPETA_PERSONAJES):
        return personajes

    for archivo in sorted(os.listdir(CARPETA_PERSONAJES)):
        if archivo.endswith(".json"):
            ruta = os.path.join(CARPETA_PERSONAJES, archivo)
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                    datos["_archivo"] = archivo
                    if isinstance(datos.get("system_prompt"), list):
                        datos["system_prompt"] = "\n".join(datos["system_prompt"])
                    if isinstance(datos.get("saludo_inicial"), list):
                        datos["saludo_inicial"] = "\n".join(datos["saludo_inicial"])
                    personajes.append(datos)
            except Exception as e:
                print(f"{Fore.RED}Error al cargar {archivo}: {e}")
    return personajes


def seleccionar_personaje():
    """Muestra un menú interactivo para elegir o crear personaje."""
    personajes = listar_personajes()

    print(f"\n{Fore.CYAN}{Style.BRIGHT}==================================================")
    print(f"{Fore.YELLOW}{Style.BRIGHT}        SELECCIÓN DE PERSONAJE DE ROL            ")
    print(f"{Fore.CYAN}{Style.BRIGHT}==================================================")

    for i, p in enumerate(personajes, start=1):
        print(f"{Fore.GREEN}[{i}] {Style.BRIGHT}{p.get('nombre', 'Sin Nombre')} {Fore.RESET}- {Fore.LIGHTBLACK_EX}{p.get('titulo', '')} ({p.get('genero', '')})")

    print(f"{Fore.MAGENTA}[P] {Style.BRIGHT}Crear un personaje personalizado")
    print(f"{Fore.BLUE}[C] {Style.BRIGHT}Cargar una partida guardada previamente")
    print(f"{Fore.RED}[S] Salir")
    print(f"{Fore.CYAN}--------------------------------------------------")

    while True:
        eleccion = input(f"{Fore.YELLOW}Elige una opción: {Fore.RESET}").strip()
        if eleccion.lower() in ["s", "salir", "exit"]:
            return None

        if eleccion.lower() == "c":
            resultado = cargar_partida()
            if resultado:
                return resultado
            print(f"{Fore.YELLOW}Selecciona un personaje de la lista o crea uno nuevo:")
            continue

        if eleccion.lower() == "p":
            nombre = input(f"{Fore.CYAN}Nombre de tu personaje: {Fore.RESET}").strip() or "Compañero"
            titulo = input(f"{Fore.CYAN}Título o profesión (ej. Hechicero errante): {Fore.RESET}").strip() or "Aventurero"
            genero = input(f"{Fore.CYAN}Género/Temática (ej. Fantasía Oscura, Sci-Fi): {Fore.RESET}").strip() or "Rol"
            prompt = input(f"{Fore.CYAN}Descripción / Personalidad del personaje: {Fore.RESET}").strip()
            saludo = input(f"{Fore.CYAN}Mensaje o saludo inicial: {Fore.RESET}").strip() or f"*{nombre} te observa en silencio y asiente con la cabeza.*"

            nuevo_p = {
                "nombre": nombre,
                "titulo": titulo,
                "genero": genero,
                "saludo_inicial": saludo,
                "system_prompt": f"Eres {nombre}, {titulo} en una historia de {genero}. {prompt}. Mantén siempre el rol usando *acciones* y diálogos."
            }

            guardar = input(f"\n{Fore.YELLOW}¿Deseas guardar este personaje en 'personajes/' para futuras partidas? (s/n): {Fore.RESET}").strip().lower()
            if guardar in ["s", "si", "y", "yes"]:
                slug = "".join(c for c in nombre.lower() if c.isalnum() or c == '_').strip() or "personaje"
                ruta_p = os.path.join(CARPETA_PERSONAJES, f"{slug}.json")
                contador = 1
                while os.path.exists(ruta_p):
                    ruta_p = os.path.join(CARPETA_PERSONAJES, f"{slug}_{contador}.json")
                    contador += 1
                try:
                    with open(ruta_p, "w", encoding="utf-8") as f:
                        json.dump(nuevo_p, f, indent=2, ensure_ascii=False)
                    print(f"{Fore.GREEN}✔ ¡Personaje guardado como {os.path.basename(ruta_p)}!")
                except Exception as e:
                    print(f"{Fore.RED}No se pudo guardar el archivo: {e}")

            return nuevo_p

        if eleccion.isdigit():
            idx = int(eleccion) - 1
            if 0 <= idx < len(personajes):
                return personajes[idx]

        print(f"{Fore.RED}Opción no válida. Intenta de nuevo.")


def enviar_mensaje_con_respaldo(proveedores, historial, nombre_personaje):
    """
    Intenta generar la respuesta con el primer proveedor disponible.
    Si falla por límite (RateLimitError, 429) o conexión, salta al siguiente.
    Aplica una ventana deslizante de memoria para no saturar tokens por minuto (TPM).
    """
    ultimo_error = None

    # Recorte inteligente de historial (Ventana deslizante)
    # Conservamos siempre historial[0] (el system_prompt con la personalidad)
    if len(historial) > MAX_MENSAJES_CONTEXTO:
        mensajes_para_enviar = [historial[0]] + historial[-(MAX_MENSAJES_CONTEXTO - 1):]
    else:
        mensajes_para_enviar = historial

    for i, prov in enumerate(proveedores):
        nombre_prov = prov["nombre"]
        cliente = prov["cliente"]
        modelo = prov["modelo"]
        temp = prov.get("temperatura", 0.8)

        try:
            # Petición con streaming para efecto máquina de escribir
            respuesta_stream = cliente.chat.completions.create(
                model=modelo,
                messages=mensajes_para_enviar,
                temperature=temp,
                stream=True
            )

            print(f"\n{Fore.YELLOW}{Style.BRIGHT}{nombre_personaje}:{Style.RESET_ALL} ", end="", flush=True)

            formateador = FormateadorRolStream()
            texto_completo = ""

            for chunk in respuesta_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    trozo = chunk.choices[0].delta.content
                    texto_completo += trozo
                    formateador.procesar(trozo)

            formateador.finalizar()
            print()  # Salto de línea al terminar
            return texto_completo, nombre_prov

        except NotFoundError as e:
            print(f"\n{Fore.RED}[Aviso: El modelo configurado en {nombre_prov} no fue encontrado: {e}]")
            ultimo_error = e
        except AuthenticationError as e:
            print(f"\n{Fore.RED}[Aviso: Clave de API no válida o expirada en {nombre_prov}: {e}]")
            ultimo_error = e
        except RateLimitError as e:
            print(f"\n{Fore.RED}[Aviso: {nombre_prov} alcanzó el límite de peticiones o tokens (429): {e}]")
            ultimo_error = e
        except APIConnectionError as e:
            print(f"\n{Fore.RED}[Aviso: Error de conexión hacia {nombre_prov}: {e}]")
            ultimo_error = e
        except APIError as e:
            print(f"\n{Fore.RED}[Aviso: Error en {nombre_prov} (Código {getattr(e, 'status_code', 'desconocido')}): {e}]")
            ultimo_error = e
        except Exception as e:
            print(f"\n{Fore.RED}[Error inesperado con {nombre_prov}: {e}]")
            ultimo_error = e

        if i + 1 < len(proveedores):
            print(f"{Fore.CYAN}[Saltando automáticamente a {proveedores[i+1]['nombre']}...]")

    print(f"\n{Fore.RED}{Style.BRIGHT}Error: Todos los proveedores configurados fallaron o agotaron su cuota.")
    if ultimo_error:
        print(f"{Fore.RED}Último detalle del fallo: {ultimo_error}")
    return None, None


def guardar_historial(nombre_personaje, historial, nombre_jugador="Tú"):
    """
    Guarda la sesión en dos formatos dentro de historiales/:
    1. Archivo .txt legible para lectura.
    2. Archivo .json estructurado para poder reanudar la partida más tarde.
    """
    if len(historial) <= 1:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre_limpio = "".join(c for c in nombre_personaje if c.isalnum() or c in (' ', '_')).rstrip()

    # 1. Guardar TXT legible
    archivo_txt = os.path.join(CARPETA_HISTORIALES, f"{nombre_limpio}_{timestamp}.txt")
    with open(archivo_txt, "w", encoding="utf-8") as f:
        f.write(f"=== SESIÓN DE ROL CON {nombre_personaje.upper()} ===\n")
        f.write(f"Jugador: {nombre_jugador}\n")
        f.write(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n")
        for msg in historial:
            rol = msg.get("role", "")
            contenido = msg.get("content", "")
            if rol == "system":
                continue
            etiqueta = nombre_jugador if rol == "user" else nombre_personaje
            f.write(f"[{etiqueta.upper()}]:\n{contenido}\n\n")

    # 2. Guardar JSON para reanudar partida
    archivo_json = os.path.join(CARPETA_HISTORIALES, f"{nombre_limpio}_{timestamp}.json")
    datos_sesion = {
        "personaje": nombre_personaje,
        "jugador": nombre_jugador,
        "fecha": datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        "historial": historial
    }
    with open(archivo_json, "w", encoding="utf-8") as f:
        json.dump(datos_sesion, f, indent=2, ensure_ascii=False)

    print(f"{Fore.LIGHTBLACK_EX}[Partida guardada en: {os.path.basename(archivo_txt)} y {os.path.basename(archivo_json)}]")
    return archivo_json


def cargar_partida():
    """Permite seleccionar y reanudar una partida guardada previamente."""
    if not os.path.exists(CARPETA_HISTORIALES):
        print(f"{Fore.YELLOW}No existe la carpeta de historiales aún.")
        return None

    archivos = [f for f in os.listdir(CARPETA_HISTORIALES) if f.endswith(".json")]
    if not archivos:
        print(f"{Fore.YELLOW}No se encontraron partidas guardadas en formato JSON.")
        return None

    # Ordenar por fecha de modificación (las más recientes primero)
    archivos.sort(key=lambda x: os.path.getmtime(os.path.join(CARPETA_HISTORIALES, x)), reverse=True)

    print(f"\n{Fore.CYAN}{Style.BRIGHT}==================================================")
    print(f"{Fore.YELLOW}{Style.BRIGHT}            PARTIDAS GUARDADAS                    ")
    print(f"{Fore.CYAN}{Style.BRIGHT}==================================================")

    partidas_info = []
    for i, archivo in enumerate(archivos[:10], start=1):
        ruta = os.path.join(CARPETA_HISTORIALES, archivo)
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
                personaje = datos.get("personaje", "Desconocido")
                fecha = datos.get("fecha", "Sin fecha")
                jugador = datos.get("jugador", "Aventurero")
                print(f"{Fore.GREEN}[{i}] {Style.BRIGHT}{personaje}{Fore.RESET} (Jugador: {jugador}) - {Fore.LIGHTBLACK_EX}{fecha}")
                partidas_info.append(datos)
        except Exception:
            continue

    if not partidas_info:
        print(f"{Fore.RED}No se pudieron leer las partidas guardadas.")
        return None

    print(f"{Fore.RED}[0] Cancelar y volver")
    print(f"{Fore.CYAN}--------------------------------------------------")

    while True:
        eleccion = input(f"{Fore.YELLOW}Elige la partida a reanudar: {Fore.RESET}").strip()
        if eleccion in ["0", "cancelar", "s"]:
            return None
        if eleccion.isdigit():
            idx = int(eleccion) - 1
            if 0 <= idx < len(partidas_info):
                datos = partidas_info[idx]
                return {
                    "nombre": datos.get("personaje", "Personaje"),
                    "_es_partida_cargada": True,
                    "jugador": datos.get("jugador", "Aventurero"),
                    "historial": datos.get("historial", [])
                }
        print(f"{Fore.RED}Opción no válida. Intenta de nuevo.")


def mostrar_ayuda():
    """Muestra la lista de comandos disponibles durante el rol."""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}--- COMANDOS DISPONIBLES ---")
    print(f"{Fore.GREEN}/guardar  {Fore.WHITE}Guarda la partida actual en historiales/ (.txt y .json)")
    print(f"{Fore.GREEN}/cargar   {Fore.WHITE}Carga una partida guardada previamente")
    print(f"{Fore.GREEN}/cambiar  {Fore.WHITE}Cambia de personaje volviendo al menú de selección")
    print(f"{Fore.GREEN}/limpiar  {Fore.WHITE}Reinicia la conversación actual desde el saludo inicial")
    print(f"{Fore.GREEN}/ayuda    {Fore.WHITE}Muestra esta lista de comandos")
    print(f"{Fore.GREEN}/salir    {Fore.WHITE}Guarda la partida y finaliza el programa")
    print(f"{Fore.CYAN}----------------------------\n")


def main():
    proveedores = inicializar_proveedores()

    # Si no hay ninguna clave configurada, guiar al usuario
    if not proveedores:
        print(f"\n{Fore.RED}{Style.BRIGHT}¡No se encontró ninguna clave de API configurada en .env!")
        print(f"{Fore.YELLOW}Para usar el bot gratuitamente, necesitas al menos una clave:")
        print(f"{Fore.CYAN}1. Groq (Recomendado): https://console.groq.com/keys (14,400 mensajes gratis)")
        print(f"{Fore.CYAN}2. OpenRouter: https://openrouter.ai/keys (Modelos gratis)")
        print(f"\n{Fore.WHITE}Abre el archivo {Fore.GREEN}.env{Fore.WHITE} en esta carpeta y pega tu clave.")
        input(f"\nPresiona Enter para salir...")
        return

    print(f"\n{Fore.GREEN}{Style.BRIGHT}✔ Proveedores activos configurados ({len(proveedores)}):")
    for p in proveedores:
        print(f"  - {Fore.CYAN}{p['nombre']} {Fore.RESET}(Modelo: {p['modelo']})")

    # Pedir nombre del jugador para mayor inmersión
    print(f"\n{Fore.YELLOW}¿Cómo se llama tu personaje o avatar en el juego?")
    nombre_jugador = input(f"{Fore.GREEN}Tu nombre (Presiona Enter para 'Aventurero'): {Fore.RESET}").strip() or "Aventurero"

    while True:
        seleccion = seleccionar_personaje()
        if not seleccion:
            print(f"\n{Fore.YELLOW}¡Hasta la próxima aventura!")
            break

        nombre = seleccion.get("nombre", "Personaje")

        if seleccion.get("_es_partida_cargada"):
            # Reanudar partida guardada
            historial = seleccion.get("historial", [])
            print(f"\n{Fore.GREEN}{Style.BRIGHT}✔ Partida con {nombre.upper()} reanudada con éxito.")
            # Mostrar los últimos 2 mensajes para poner en contexto
            for msg in historial[-2:]:
                rol = msg.get("role")
                if rol == "assistant":
                    print(f"\n{Fore.YELLOW}{Style.BRIGHT}{nombre}:{Fore.RESET}\n{msg.get('content')}")
                elif rol == "user":
                    print(f"\n{Fore.GREEN}{Style.BRIGHT}{nombre_jugador}:{Fore.RESET} {msg.get('content')}")
        else:
            saludo = seleccion.get("saludo_inicial", f"*{nombre} te observa en silencio.*")
            prompt_base = seleccion.get("system_prompt", f"Eres {nombre}. Mantén siempre el rol.")
            # Añadir contexto del jugador al system prompt
            prompt_completo = f"{prompt_base}\nEl usuario interactúa contigo bajo el nombre o personaje de '{nombre_jugador}'."

            historial = [
                {"role": "system", "content": prompt_completo},
                {"role": "assistant", "content": saludo}
            ]

            print(f"\n{Fore.CYAN}{Style.BRIGHT}==================================================")
            print(f"{Fore.GREEN}{Style.BRIGHT}       INICIANDO ESCENARIO CON: {nombre.upper()}  ")
            print(f"{Fore.LIGHTBLACK_EX}Comandos: {Fore.WHITE}/guardar {Fore.LIGHTBLACK_EX}| {Fore.WHITE}/cargar {Fore.LIGHTBLACK_EX}| {Fore.WHITE}/cambiar {Fore.LIGHTBLACK_EX}| {Fore.WHITE}/salir {Fore.LIGHTBLACK_EX}| {Fore.WHITE}/ayuda")
            print(f"{Fore.CYAN}{Style.BRIGHT}==================================================")

            # Imprimir saludo inicial formateado
            print(f"\n{Fore.YELLOW}{Style.BRIGHT}{nombre}:{Style.RESET_ALL}")
            formateador = FormateadorRolStream()
            formateador.procesar(saludo)
            formateador.finalizar()
            print()

        # Bucle de interacción con el personaje
        cambiar_personaje = False
        while True:
            try:
                print(f"\n{Fore.GREEN}{Style.BRIGHT}{nombre_jugador}:{Fore.RESET} ", end="")
                entrada = input().strip()

                if not entrada:
                    continue

                cmd = entrada.lower()

                if cmd in ["/salir", "salir", "exit", "quit"]:
                    guardar_historial(nombre, historial, nombre_jugador)
                    print(f"\n{Fore.YELLOW}Partida finalizada. ¡Hasta la próxima!")
                    return

                if cmd == "/ayuda":
                    mostrar_ayuda()
                    continue

                if cmd == "/guardar":
                    guardar_historial(nombre, historial, nombre_jugador)
                    continue

                if cmd == "/cargar":
                    guardar_historial(nombre, historial, nombre_jugador)
                    nueva_sesion = cargar_partida()
                    if nueva_sesion:
                        seleccion = nueva_sesion
                        nombre = seleccion.get("nombre", "Personaje")
                        historial = seleccion.get("historial", [])
                        print(f"\n{Fore.GREEN}{Style.BRIGHT}✔ Partida con {nombre.upper()} reanudada.")
                        for msg in historial[-2:]:
                            rol = msg.get("role")
                            if rol == "assistant":
                                print(f"\n{Fore.YELLOW}{Style.BRIGHT}{nombre}:{Fore.RESET}\n{msg.get('content')}")
                            elif rol == "user":
                                print(f"\n{Fore.GREEN}{Style.BRIGHT}{nombre_jugador}:{Fore.RESET} {msg.get('content')}")
                    continue

                if cmd == "/cambiar":
                    guardar_historial(nombre, historial, nombre_jugador)
                    cambiar_personaje = True
                    break

                if cmd == "/limpiar":
                    prompt_reinicio = historial[0]["content"]
                    saludo_reinicio = seleccion.get("saludo_inicial", f"*{nombre} te observa en silencio.*")
                    historial = [
                        {"role": "system", "content": prompt_reinicio},
                        {"role": "assistant", "content": saludo_reinicio}
                    ]
                    print(f"\n{Fore.CYAN}[Historial reiniciado. Escena en blanco.]")
                    print(f"\n{Fore.YELLOW}{Style.BRIGHT}{nombre}:{Style.RESET_ALL}")
                    formateador = FormateadorRolStream()
                    formateador.procesar(saludo_reinicio)
                    formateador.finalizar()
                    print()
                    continue

                # Agregar mensaje del usuario al historial
                historial.append({"role": "user", "content": entrada})

                # Generar respuesta con failover multi-API
                respuesta, prov_usado = enviar_mensaje_con_respaldo(proveedores, historial, nombre)

                if respuesta:
                    historial.append({"role": "assistant", "content": respuesta})
                else:
                    # Si fallaron todas las APIs, deshacer el último mensaje del usuario para no corromper la memoria
                    historial.pop()

            except KeyboardInterrupt:
                guardar_historial(nombre, historial, nombre_jugador)
                print(f"\n\n{Fore.YELLOW}Sesión interrumpida. Historial guardado.")
                return

        if not cambiar_personaje:
            break


if __name__ == "__main__":
    main()
