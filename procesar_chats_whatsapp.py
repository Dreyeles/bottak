"""
=============================================================================
EXTRACTOR DE MEMORIAS DE CHATS DE WHATSAPP PARA ADA LIZ
=============================================================================
Lee exportaciones de WhatsApp (.txt), limpia el ruido y usa Groq para extraer
cronológicamente las anécdotas, recuerdos y formas de hablar reales entre Drey y Ada,
guardándolos en personajes/ada_liz_contexto.md.
=============================================================================
"""

import os
import re
import sys
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import colorama
from colorama import Fore, Style

colorama.init(autoreset=True)

DIRECTORIO_ACTUAL = os.path.dirname(os.path.abspath(__file__))
RUTA_ENV = os.path.join(DIRECTORIO_ACTUAL, ".env")
load_dotenv(RUTA_ENV)

CARPETA_CHATS_DEFAULT = r"c:\Users\Drewg\Downloads\Chat_Dividido\Chat_Dividido"
ARCHIVO_CONTEXTO_MD = os.path.join(DIRECTORIO_ACTUAL, "personajes", "ada_liz_contexto.md")


def inicializar_ia():
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        return OpenAI(api_key=groq_key, base_url="https://api.groq.com/openai/v1"), "openai/gpt-oss-120b"
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if openrouter_key:
        return OpenAI(api_key=openrouter_key, base_url="https://openrouter.ai/api/v1"), "nvidia/nemotron-3-ultra-550b-a55b:free"
    return None, None


def limpiar_chat_whatsapp(ruta_archivo):
    """Limpia avisos del sistema, multimedia y filtra conversaciones con sustancia."""
    if not os.path.exists(ruta_archivo):
        return None

    lineas_limpias = []
    patron_sistema = re.compile(r"(Los mensajes y las llamadas están cifrados|<Multimedia omitido>|Se eliminó este mensaje|Llamada perdida|cambió el código de seguridad)", re.IGNORECASE)
    patron_mensaje = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4},.*?[-\]]\s*(.*?):\s*(.*)$")

    with open(ruta_archivo, "r", encoding="utf-8", errors="ignore") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or patron_sistema.search(linea):
                continue
            match = patron_mensaje.match(linea)
            if match:
                emisor, texto = match.groups()
                texto = texto.strip()
                # Omitir textos ultrasimples repetitivos si están aislados
                if texto and len(texto) > 1:
                    lineas_limpias.append(f"{emisor}: {texto}")
            else:
                # Continuación de mensaje multilínea
                if lineas_limpias and len(linea) > 2:
                    lineas_limpias[-1] += f" {linea}"

    return lineas_limpias


def extraer_recuerdos_de_bloque(cliente, modelo, bloque_texto, etiqueta_mes):
    """Pide a la IA que destile los recuerdos y anécdotas clave de un bloque de chat."""
    prompt = f"""Eres un asistente de memoria personal para un bot de rol de pareja.
A continuación tienes un fragmento de conversaciones de WhatsApp de {etiqueta_mes} entre Drey (Drey.e) y su novia Ada (Ada Liz).

Tu objetivo es extraer de forma concisa y emotiva:
1. ANÉCDOTAS Y RECUERDOS REALES: Hechos concretos que vivieron, planes que hicieron, cosas que les pasaron, lugares o situaciones mencionadas.
2. APODOS Y LENGUAJE CARACTERÍSTICO: Apodos que se dijeron, expresiones típicas (ej: :3, :v, holo, amorshito) y bromas internas.
3. DINÁMICA DE LA RELACIÓN: Momentos dulces, pequeñas discusiones cariñosas o temas recurrentes.

Reglas de salida:
- Responde directamente con viñetas con formato Markdown (- ...).
- Escribe en tono de memoria en tercera persona ("En este mes hablaron de...", "Drey le dijo que...", "Ada solía...").
- NO inventes nada que no esté en el texto.
- Sé breve y conciso (máximo 8 a 12 viñetas clave por bloque).

CHAT:
{bloque_texto}
"""
    try:
        res = cliente.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error extrayendo con IA: {e}")
        return None


def procesar_archivo_mes(ruta_archivo, cliente, modelo):
    """Procesa un archivo de chat mensual completo dividiéndolo en partes digestibles."""
    nombre_archivo = os.path.basename(ruta_archivo)
    etiqueta_mes = nombre_archivo.replace("Chat_", "").replace(".txt", "")

    print(f"\n{Fore.CYAN}📖 Leyendo {Fore.YELLOW}{nombre_archivo}{Fore.CYAN}...")
    lineas = limpiar_chat_whatsapp(ruta_archivo)
    if not lineas:
        print(f"{Fore.RED}No se encontraron mensajes válidos en {nombre_archivo}")
        return None

    print(f"{Fore.GREEN}✔ Mensajes limpios encontrados: {len(lineas)}")

    # Tomar muestras o dividir en bloques de ~350 mensajes para no saturar tokens
    bloques = []
    tamano_bloque = 350
    for i in range(0, len(lineas), tamano_bloque):
        bloques.append("\n".join(lineas[i:i + tamano_bloque]))

    print(f"{Fore.MAGENTA}⏳ Analizando {len(bloques)} bloque(s) con {modelo}...")

    recuerdos_mes = []
    for num_b, bloque in enumerate(bloques[:4], start=1):  # Tomar hasta 4 bloques más representativos
        print(f"  - Procesando parte {num_b}/{min(len(bloques), 4)}...", end="", flush=True)
        res = extraer_recuerdos_de_bloque(cliente, modelo, bloque, f"el mes {etiqueta_mes}")
        if res:
            recuerdos_mes.append(res)
            print(f" {Fore.GREEN}✔")
        else:
            print(f" {Fore.RED}✘")

    if not recuerdos_mes:
        return None

    # Unir recuerdos del mes
    contenido_final = f"\n\n### 📅 Recuerdos de {etiqueta_mes}\n" + "\n".join(recuerdos_mes) + "\n"
    return contenido_final


def guardar_en_contexto_md(contenido):
    """Inserta los recuerdos en ada_liz_contexto.md bajo la sección de memorias."""
    if not os.path.exists(ARCHIVO_CONTEXTO_MD):
        print(f"{Fore.RED}No se encontró {ARCHIVO_CONTEXTO_MD}")
        return

    with open(ARCHIVO_CONTEXTO_MD, "r", encoding="utf-8") as f:
        texto = f.read()

    # Buscar la sección ## 📖 MEMORIAS Y ANÉCDOTAS COMPARTIDAS
    marcador = "## 📖 MEMORIAS Y ANÉCDOTAS COMPARTIDAS"
    if marcador in texto:
        partes = texto.split(marcador, 1)
        nuevo_texto = partes[0] + marcador + "\n" + contenido + partes[1]
    else:
        nuevo_texto = texto + "\n\n" + marcador + "\n" + contenido

    with open(ARCHIVO_CONTEXTO_MD, "w", encoding="utf-8") as f:
        f.write(nuevo_texto)

    print(f"\n{Fore.GREEN}{Style.BRIGHT}✔ ¡Memorias guardadas con éxito en: personajes/ada_liz_contexto.md!")


def main():
    cliente, modelo = inicializar_ia()
    if not cliente:
        print(f"{Fore.RED}No se encontró API Key configurada.")
        return

    carpeta_chats = CARPETA_CHATS_DEFAULT
    if not os.path.exists(carpeta_chats):
        print(f"{Fore.RED}No se encontró la carpeta: {carpeta_chats}")
        return

    archivos = [f for f in sorted(os.listdir(carpeta_chats)) if f.startswith("Chat_") and f.endswith(".txt")]
    if not archivos:
        print(f"{Fore.RED}No se encontraron archivos de chat en la carpeta.")
        return

    print(f"\n{Fore.CYAN}{Style.BRIGHT}==================================================")
    print(f"{Fore.YELLOW}{Style.BRIGHT}    EXTRACTOR DE RECUERDOS DE WHATSAPP           ")
    print(f"{Fore.CYAN}{Style.BRIGHT}==================================================")
    print(f"Archivos mensuales disponibles ({len(archivos)}):\n")

    for i, a in enumerate(archivos, start=1):
        print(f"{Fore.GREEN}[{i}] {Style.BRIGHT}{a}")

    print(f"\n{Fore.MAGENTA}[T] Procesar TODOS los meses en lote")
    print(f"{Fore.RED}[S] Salir")
    print(f"{Fore.CYAN}--------------------------------------------------")

    eleccion = input(f"{Fore.YELLOW}Elige el número de archivo para probar (ej: 2 para Chat_2021-01.txt): {Fore.RESET}").strip()

    if eleccion.lower() in ["s", "salir"]:
        return

    if eleccion.isdigit():
        idx = int(eleccion) - 1
        if 0 <= idx < len(archivos):
            ruta_elegida = os.path.join(carpeta_chats, archivos[idx])
            recuerdos = procesar_archivo_mes(ruta_elegida, cliente, modelo)
            if recuerdos:
                print(f"\n{Fore.YELLOW}Vista previa de lo extraído:\n{Fore.WHITE}{recuerdos[:600]}...\n")
                guardar = input(f"{Fore.GREEN}¿Deseas guardar estos recuerdos en ada_liz_contexto.md? (s/n): {Fore.RESET}").strip().lower()
                if guardar in ["s", "si", "y", "yes"]:
                    guardar_en_contexto_md(recuerdos)
            return

    print(f"{Fore.RED}Opción no válida.")


if __name__ == "__main__":
    main()
