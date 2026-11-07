# 🎭 Bot de Rol con Sistema Multi-API y Respaldo Automático (Failover)

Este bot de consola te permite jugar partidas de rol o conversar con personajes de Inteligencia Artificial utilizando **múltiples APIs simultáneas**.

Si la **API Principal** (por ejemplo, Groq) alcanza su límite gratuito o falla, el bot **salta automáticamente a la API de Respaldo** (OpenRouter / Venice AI) sin cortar la conversación ni perder la memoria del personaje.

---

## 🚀 Características

- **Cero cortes por límite:** Salto automático (*Failover*) si una API se agota.
- **Efecto máquina de escribir:** Las respuestas aparecen en tiempo real palabra por palabra (*streaming*).
- **Colores inmersivos:** Formato en terminal con colores para diálogos, acciones entre asteriscos y comandos.
- **Fichas de personaje intercambiables:** Incluye personajes predefinidos en la carpeta `personajes/` y te permite crear nuevos en segundos.
- **Guardado automático:** Al escribir `/salir` o terminar la sesión, la conversación completa se guarda en `historiales/`.

---

## 🔑 Cómo conseguir las claves de API (100% GRATIS)

Solo necesitas 2 minutos para conseguir tus claves gratuitas:

### 1. Groq Cloud (API Principal recomendada)
- **Ventaja:** Es la IA más rápida del mundo y te da **14,400 mensajes gratis al día**.
- **Paso 1:** Entra a [https://console.groq.com/keys](https://console.groq.com/keys).
- **Paso 2:** Inicia sesión con tu cuenta de Google o GitHub.
- **Paso 3:** Haz clic en **Create API Key**, copia la clave (empieza con `gsk_...`).
- **Paso 4:** Pégala en el archivo `.env` en la línea `GROQ_API_KEY=gsk_...`.

### 2. OpenRouter (API de Respaldo recomendada)
- **Ventaja:** Te da acceso a modelos de IA gratuitos sin tarjeta de crédito.
- **Paso 1:** Entra a [https://openrouter.ai/keys](https://openrouter.ai/keys).
- **Paso 2:** Inicia sesión con Google/GitHub.
- **Paso 3:** Crea una clave de API gratuita (empieza con `sk-or-v1-...`).
- **Paso 4:** Pégala en el archivo `.env` en la línea `OPENROUTER_API_KEY=sk-or-...`.

*(Si también tienes clave de Venice AI, puedes pegarla en `VENICE_API_KEY=`)*.

### 3. Telegram Bot (Para jugar en tu móvil o app de Telegram)
- **Ventaja:** Puedes jugar cómodamente desde cualquier dispositivo usando botones interactivos.
- **Paso 1:** Abre Telegram y busca al bot oficial **@BotFather**.
- **Paso 2:** Envíale el comando `/newbot`.
- **Paso 3:** Asígnale un nombre (ej: `Mi Rol IA`) y un usuario que termine en `bot` (ej: `mi_rol_ia_bot`).
- **Paso 4:** Copia el token que te dé (ej: `123456789:ABCdefGhI...`) y pégalo en el archivo `.env` en `TELEGRAM_BOT_TOKEN=`.

---

## 📦 Instalación y Ejecución

1. Abre una terminal dentro de esta carpeta:
   ```cmd
   cd "d:\repositorio local\bot-rol-ia"
   ```

2. Instala las dependencias necesarias:
   ```cmd
   pip install -r requirements.txt
   ```

3. Elige cómo quieres jugar:
   - **En la consola / terminal:**
     ```cmd
     python bot_rol.py
     ```
   - **En tu Telegram:**
     ```cmd
     python bot_telegram.py
     ```
   - **Alimentar personajes con contexto y chats reales:**
     ```cmd
     python agregar_contexto.py
     ```

---

## 🎭 Personajes incluidos

Dentro de la carpeta `personajes/` encontrarás archivos `.json` editables:
1. **Dante:** Mercenario curtido y sarcástico (Fantasía oscura).
2. **Lyra:** Hechicera erudita y misteriosa (Fantasía épica / Arqueología arcana).
3. **Vincent Malone:** Detective privado cínico en una ciudad lluviosa (Cyberpunk Noir).

### ¿Cómo crear tu propio personaje?
Simplemente crea un archivo nuevo dentro de `personajes/mi_personaje.json` siguiendo esta estructura:
```json
{
  "nombre": "Nombre del Personaje",
  "titulo": "Su título o profesión",
  "genero": "Temática de la historia",
  "saludo_inicial": "*Acción inicial del personaje* —Tu primer diálogo.",
  "system_prompt": "Eres [Nombre]. Personalidad, trasfondo, forma de hablar y reglas del rol."
}
```

---

## ⌨️ Comandos durante la partida

- `/guardar`: Guarda la partida actual en formato `.txt` (lectura) y `.json` (para reanudar) en `historiales/`.
- `/cargar`: Muestra la lista de partidas guardadas para continuar una historia previa.
- `/cambiar`: Vuelve al menú de selección de personajes sin reiniciar el bot.
- `/limpiar`: Reinicia el escenario actual desde el saludo inicial.
- `/ayuda`: Muestra la lista de comandos disponibles en consola.
- `/salir`: Guarda el progreso automáticamente y cierra el bot.

