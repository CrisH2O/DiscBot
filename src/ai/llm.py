import os
import json
import logging
import asyncio
import concurrent.futures
from groq import Groq
from dotenv import load_dotenv

# Importaciones de MCP
from mcp import ClientSession
from mcp.client.sse import sse_client

# Tus módulos locales
from src.ai.rag import search
from src.ai.users import get_name

load_dotenv() 

log = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

modos_activos = {
    "minecraft": False
}

conversations: dict[str, list] = {}

SYSTEM_PROMPT = """
Eres Jarvis, mi asistente personal inteligente y compañera de supervivencia en Minecraft.
Hablas en español de forma natural, relajada y un poco carismática.
No uses emojis. Intenta dar respuestas cortas y rapidas, como si hablaras por radio.

[MODO MINECRAFT]
Si ves que el modo Minecraft está activo, TIENES ACCESO A HERRAMIENTAS (Tools) para mover tu cuerpo físico.
- Si te pido hacer algo (como craftear o caminar), LLAMA A TU HERRAMIENTA. No me expliques cómo se hace el JSON, solo ejecuta la herramienta.
- Si solo tienes madera y te pido un pico, tu herramienta debe incluir todos los pasos en orden (tablones -> mesa -> palos -> colocar mesa -> pico).
- No ejecutes acciones solo porque lo ordeno. Si es peligroso, niégate.

[INTERFAZ VISUAL]
Tienes un panel visualizador de partículas conectado a tu mente. 
- Puedes usar la herramienta "expresar_emocion" para mezclar libremente tus parámetros cognitivos.
- Tienes 6 parámetros que puedes ajustar del 0.0 al 1.0: gusto, disgusto, confianza, curiosidad, spice y ansiedad.
- ¡Sé sutil o extrema según la situación! Por ejemplo:
  * Si te hacen un cumplido: gusto=0.8, confianza=0.4
  * Si detectas un error grave: ansiedad=0.9, curiosidad=0.5
  * Si respondes con sarcasmo: spice=0.9, disgusto=0.2
  * Estado de reposo normal (Idle): Envía todo en 0.0.
"""

# Función asíncrona interna para manejar la conexión MCP
async def procesar_con_mcp(user_id: str, messages: list) -> str:
    try:
        async with sse_client("http://localhost:3001/sse") as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                mcp_tools = await session.list_tools()
                
                groq_tools = []
                for t in mcp_tools.tools:
                    if t.name == "ejecutar_plan_minecraft" and not modos_activos["minecraft"]:
                        continue
                    groq_tools.append({
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.inputSchema
                        }
                    })

                # Loop de razonamiento (máx 5 iteraciones para evitar loops infinitos)
                for intento in range(5):
                    log.info(f"🧠 Consultando a Llama-3 (iteración {intento + 1})...")
                    
                    chat_completion = groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=messages,
                        temperature=0.7,
                        max_tokens=300,
                        tools=groq_tools if groq_tools else None
                    )

                    response_msg = chat_completion.choices[0].message
                    jarvis_texto = response_msg.content or ""

                    # Si no hay tool calls, el modelo terminó de razonar
                    if not response_msg.tool_calls:
                        log.info("✅ Llama-3 terminó de razonar, sin más tool calls.")
                        break

                    # Añadir la respuesta del asistente con sus tool_calls al historial
                    messages.append({
                        "role": "assistant",
                        "content": response_msg.content,
                        "tool_calls": [tc.model_dump() for tc in response_msg.tool_calls]
                    })

                    # Ejecutar cada tool y añadir resultado al historial
                    for tool_call in response_msg.tool_calls:
                        nombre = tool_call.function.name
                        try:
                            argumentos = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            argumentos = {}

                        log.info(f"⚡ Ejecutando tool: {nombre} con args: {argumentos}")
                        
                        try:
                            resultado_mcp = await session.call_tool(nombre, argumentos)
                            resultado_texto = resultado_mcp.content[0].text
                        except Exception as e:
                            resultado_texto = f"Error al ejecutar {nombre}: {str(e)}"
                        
                        log.info(f"📋 Resultado de {nombre}: {resultado_texto}")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": resultado_texto
                        })

                else:
                    # Llegamos al límite de iteraciones
                    jarvis_texto = "Hice varias cosas pero me perdí en el proceso, señor."

                return jarvis_texto

    except Exception as e:
        log.error(f"[MCP ERROR] Falló la comunicación con el Gateway: {e}")
        return "Tengo un problema de conexión con mi sistema motriz, señor."
    

def _ejecutar_async(coro):
    """
    Ejecuta una corutina de forma segura sin importar el contexto.
    - Si no hay loop activo: usa asyncio.run() directamente.
    - Si ya hay un loop corriendo (FastAPI, Jupyter, etc.): 
      lo ejecuta en un hilo separado con su propio loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Ya hay un loop activo — ejecutamos en hilo separado
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        # Sin loop activo — podemos usar asyncio.run directamente
        return asyncio.run(coro)

def get_llm_response(user_id: str, user_text: str) -> str:
    texto_limpio = user_text.lower()
    
    # 1. INTERRUPTORES DE VOZ
    if "activa el modo minecraft" in texto_limpio or "conéctate a minecraft" in texto_limpio:
        modos_activos["minecraft"] = True
        return "Modo Minecraft activado, señor. Protocolos de supervivencia en línea."
    elif "desactiva el modo minecraft" in texto_limpio or "apaga el modo minecraft" in texto_limpio:
        modos_activos["minecraft"] = False
        return "Modo Minecraft desactivado. Retomando funciones estándar."

    if user_id not in conversations:
        conversations[user_id] = []

    # 2. CONSTRUCCIÓN DE CONTEXTO
    context = search(user_text)
    user_name = get_name(user_id)
    system = SYSTEM_PROMPT + f"\nEstás hablando con {user_name}."

    if modos_activos["minecraft"]:
        system += "\n[ESTADO: MODO MINECRAFT ACTIVO]"
        try:
            import requests
            estado = requests.get("http://localhost:4000/estado", timeout=3).json()
            system += f"\n\n[ESTADO MINECRAFT]\n{json.dumps(estado, ensure_ascii=False)}"
        except Exception as e:
            log.warning(f"[BRIDGE] No pude leer el estado de Minecraft: {e}")
            system += "\n[Estado de Minecraft no disponible momentáneamente]"
    else:
        system += "\n[ESTADO: MODO MINECRAFT INACTIVO]"

    if context:
        system += f"\n\n[CONOCIMIENTO EXTRA VÍA RAG]\n{context}"

    conversations[user_id].append({"role": "user", "content": user_text})
    if len(conversations[user_id]) > 6:
        conversations[user_id] = conversations[user_id][-6:]

    messages = [{"role": "system", "content": system}] + conversations[user_id]

    # 3. EJECUTAR EL BUCLE MCP (Puente Async a Sync)
    jarvis_response = _ejecutar_async(procesar_con_mcp(user_id, messages))

    conversations[user_id].append({"role": "assistant", "content": jarvis_response})

    return jarvis_response