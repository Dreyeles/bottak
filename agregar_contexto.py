"""
=============================================================================
HERRAMIENTA PARA AÑADIR CONTEXTO Y CHATS A TUS PERSONAJES
=============================================================================
Este script te permite alimentar a tus personajes (como Ada Liz) con fragmentos
de conversaciones reales, anécdotas, recuerdos y contexto poco a poco desde
la consola o cargando archivos de texto.
=============================================================================
"""

import os
import sys
import json
from datetime import datetime
from dotenv import load_dotenv
import colorama
from colorama import Fore, Style
from openai import OpenAI

# Inicializar colorama
colorama.init(autoreset=True)

DIRECTORIO_ACTUAL = os.path.dirname(os.path.abspath(__file__))
RUTA_ENV = os.path.join(DIRECTORIO_ACTUAL, ".env")
load_dotenv(RUTA_ENV)

CARPETA_PERSONAJES = os.path.join(DIRECTORIO_ACTUAL, "personajes")


def inicializar_cliente_ia():
    """Obtiene cliente para resumir o procesar chats con IA si se desea."""
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        return OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1"), "openai/gpt-oss-120b"
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if openrouter_key:
        return OpenAI(api_key=openrouter_key, base_url="https://openrouter.ai/api/v1"), "nvidia/nemotron-3.5-lightning:free"
    return None, None


def listar_personajes():
    """Devuelve la lista de archivos JSON en personajes/."""
    archivos = [f for f in sorted(os.listdir(CARPETA_PERSONAJES)) if f.endswith(".json")]
    personajes = []
    for arch in archivos:
        ruta = os.path.join(CARPETA_PERSONAJES, arch)
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                datos = json.load(f)
                datos["_archivo"] = arch
                personajes.append(datos)
        except Exception:
            continue
    return personajes


def leer_texto_multilinea(indicacion="Pega o escribe tu texto a continuación (Escribe 'FIN' en una línea vacía al terminar):"):
    """Permite pegar fragmentos largos de texto o chats con múltiples saltos de línea."""
    print(f"\n{Fore.CYAN}{indicacion}")
    print(f"{Fore.LIGHTBLACK_EX}------------------------------------------------------------")
    lineas = []
    while True:
        try:
            linea = input()
            if linea.strip().upper() == "FIN":
                break
            lineas.append(linea)
        except EOFError:
            break
        except KeyboardInterrupt:
            print(f"\n{Fore.RED}Entrada cancelada.")
            return None
    print(f"{Fore.LIGHTBLACK_EX}------------------------------------------------------------")
    texto = "\n".join(lineas).strip()
    return texto if texto else None


def extraer_recuerdos_con_ia(texto_chat, nombre_personaje):
    """Utiliza Groq para destilar un chat largo en recuerdos, apodos y dinámicas clave."""
    cliente, modelo = inicializar_cliente_ia()
    if not cliente:
        print(f"{Fore.YELLOW}No hay cliente de IA configurado para procesar. Se guardará como texto crudo.")
        return texto_chat

    print(f"\n{Fore.YELLOW}⏳ Analizando conversación con IA para extraer recuerdos y forma de hablar...")
    prompt = (
        f"A continuación tienes un fragmento de conversación real entre Drey y su pareja {nombre_personaje}.\n"
        "Extrae y resume en puntos clave:\n"
        "1. Hechos, recuerdos o temas conversados que deben recordar.\n"
        "2. Apodos, bromas internas o expresiones que usaron.\n"
        "3. Tono emocional y dinámica de la charla.\n"
        "Responde en español de forma directa y concisa para añadirlo al system prompt del personaje.\n\n"
        f"CHAT:\n{texto_chat}"
    )

    try:
        res = cliente.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        print(f"{Fore.RED}Error al procesar con IA: {e}. Se usará el texto original.")
        return texto_chat


def insertar_contexto_en_personaje(datos_personaje, nuevo_bloque, etiqueta="Recuerdo / Chat"):
    """Inserta el nuevo bloque de contexto en el system_prompt del personaje de forma limpia."""
    fecha_hoy = datetime.now().strftime("%d/%m/%Y %H:%M")
    lineas_nuevas = [
        "",
        f"--- [{etiqueta.upper()} - {fecha_hoy}] ---"
    ]
    for linea in nuevo_bloque.splitlines():
        lineas_nuevas.append(f"• {linea}" if not linea.startswith("•") and not linea.startswith("-") and linea.strip() else linea)

    prompt = datos_personaje.get("system_prompt")

    # Si es lista de strings
    if isinstance(prompt, list):
        # Buscar el delimitador de contexto
        indice_cierre = -1
        for i, l in enumerate(prompt):
            if "=====" in l and i > 5:
                indice_cierre = i

        if indice_cierre != -1:
            # Insertar justo antes del cierre
            for k, lin in enumerate(lineas_nuevas):
                prompt.insert(indice_cierre + k, lin)
        else:
            prompt.extend(lineas_nuevas)

        datos_personaje["system_prompt"] = prompt

    # Si es un solo string
    elif isinstance(prompt, str):
        datos_personaje["system_prompt"] = prompt + "\n" + "\n".join(lineas_nuevas)

    # Guardar en el archivo JSON
    ruta_archivo = os.path.join(CARPETA_PERSONAJES, datos_personaje["_archivo"])
    datos_guardar = {k: v for k, v in datos_personaje.items() if k != "_archivo"}

    with open(ruta_archivo, "w", encoding="utf-8") as f:
        json.dump(datos_guardar, f, indent=2, ensure_ascii=False)

    print(f"\n{Fore.GREEN}{Style.BRIGHT}✔ ¡Contexto añadido y guardado exitosamente en {datos_personaje['_archivo']}!")


def ver_contexto_actual(datos_personaje):
    """Muestra el contexto que tiene actualmente guardado el personaje."""
    prompt = datos_personaje.get("system_prompt")
    print(f"\n{Fore.CYAN}{Style.BRIGHT}==================================================")
    print(f"{Fore.YELLOW}{Style.BRIGHT}   CONTEXTO ACTUAL DE: {datos_personaje.get('nombre', '').upper()}")
    print(f"{Fore.CYAN}{Style.BRIGHT}==================================================")
    if isinstance(prompt, list):
        for linea in prompt:
            print(f"{Fore.WHITE}{linea}")
    else:
        print(f"{Fore.WHITE}{prompt}")
    print(f"{Fore.CYAN}{Style.BRIGHT}==================================================\n")


def main():
    while True:
        personajes = listar_personajes()
        if not personajes:
            print(f"{Fore.RED}No se encontraron personajes en la carpeta personajes/.")
            return

        print(f"\n{Fore.CYAN}{Style.BRIGHT}==================================================")
        print(f"{Fore.YELLOW}{Style.BRIGHT}    GESTOR DE CONTEXTO Y RECUERDOS DE CHAT       ")
        print(f"{Fore.CYAN}{Style.BRIGHT}==================================================")
        print(f"{Fore.WHITE}Selecciona el personaje al que deseas agregar contexto:\n")

        for i, p in enumerate(personajes, start=1):
            print(f"{Fore.GREEN}[{i}] {Style.BRIGHT}{p.get('nombre', 'Sin Nombre')} {Fore.LIGHTBLACK_EX}({p['_archivo']})")

        print(f"{Fore.RED}[S] Salir")
        print(f"{Fore.CYAN}--------------------------------------------------")

        eleccion = input(f"{Fore.YELLOW}Elige un personaje: {Fore.RESET}").strip()
        if eleccion.lower() in ["s", "salir", "exit"]:
            print(f"{Fore.YELLOW}Hasta luego.")
            break

        if not eleccion.isdigit() or not (1 <= int(eleccion) <= len(personajes)):
            print(f"{Fore.RED}Opción no válida.")
            continue

        p_seleccionado = personajes[int(eleccion) - 1]
        nombre_p = p_seleccionado.get("nombre", "Personaje")

        while True:
            print(f"\n{Fore.CYAN}--- GESTIONAR CONTEXTO: {Fore.YELLOW}{nombre_p.upper()} {Fore.CYAN}---")
            print(f"{Fore.GREEN}[1] {Fore.WHITE}Pegar fragmento de chat o recuerdo directamente en consola")
            print(f"{Fore.GREEN}[2] {Fore.WHITE}Cargar conversación desde un archivo de texto (.txt)")
            print(f"{Fore.GREEN}[3] {Fore.WHITE}Ver el contexto / personalidad actual")
            print(f"{Fore.RED}[0] {Fore.WHITE}Volver al menú de personajes")

            sub_op = input(f"\n{Fore.YELLOW}Elige una opción: {Fore.RESET}").strip()

            if sub_op == "0":
                break

            if sub_op == "3":
                ver_contexto_actual(p_seleccionado)
                continue

            texto_a_insertar = None
            etiqueta = "Conversación / Recuerdo"

            if sub_op == "1":
                etiqueta = input(f"{Fore.CYAN}Título o etiqueta para este fragmento (ej: 'Charla sobre películas', 'Viaje a la playa', o Enter): {Fore.RESET}").strip() or "Recuerdo de Chat"
                texto_a_insertar = leer_texto_multilinea("Pega tu conversación o texto aquí. Cuando termines, escribe 'FIN' y presiona Enter:")

            elif sub_op == "2":
                ruta_txt = input(f"{Fore.CYAN}Introduce la ruta o nombre del archivo .txt (ej: mi_chat.txt): {Fore.RESET}").strip().strip('"')
                if not os.path.exists(ruta_txt):
                    print(f"{Fore.RED}No se encontró el archivo: {ruta_txt}")
                    continue
                try:
                    with open(ruta_txt, "r", encoding="utf-8") as f:
                        texto_a_insertar = f.read().strip()
                    etiqueta = os.path.basename(ruta_txt)
                except Exception as e:
                    print(f"{Fore.RED}Error al leer el archivo: {e}")
                    continue

            if not texto_a_insertar:
                print(f"{Fore.YELLOW}No se introdujo ningún texto.")
                continue

            # Preguntar si procesar con IA o guardar en crudo
            print(f"\n{Fore.YELLOW}¿Cómo deseas guardar este fragmento?")
            print(f"{Fore.CYAN}[1] Como texto crudo / ejemplo literal de conversación")
            print(f"{Fore.CYAN}[2] {Style.BRIGHT}Procesado con IA (Extrae recuerdos, apodos y hechos clave para ahorrar espacio)")

            modo_guardado = input(f"{Fore.YELLOW}Opción (1/2, Enter para 1): {Fore.RESET}").strip()
            if modo_guardado == "2":
                bloque_final = extraer_recuerdos_con_ia(texto_a_insertar, nombre_p)
            else:
                bloque_final = texto_a_insertar

            insertar_contexto_en_personaje(p_seleccionado, bloque_final, etiqueta)


if __name__ == "__main__":
    main()

