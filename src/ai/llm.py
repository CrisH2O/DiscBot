import os
import json
import logging
from pathlib import Path
from groq import Groq
from dotenv import load_dotenv
from src.ai.events import EventEmitter

# Importaciones de MCP
from mcp import ClientSession
from mcp.client.sse import sse_client

# Tus módulos locales
from src.ai.rag import search
from src.ai.users import get_name

load_dotenv()
log = logging.getLogger(__name__)

class JarvisAgent:
    def __init__(self, mcp_url: str = "http://localhost:3001/sse"):
        self.mcp_url = mcp_url
        self.groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        self.model_name = "llama-3.3-70b-versatile"
        self.events = EventEmitter()
        
        # Estado del agente encapsulado (Adiós globales)
        self.modos_activos = {
            "minecraft": False
        }
        self.conversations = {}
        
        # Ruta base para la carga dinámica de prompts
        self.prompts_dir = Path(__file__).parent / "prompts"

    def build_system_prompt(self, user_name: str) -> str:
        """Carga y concatena dinámicamente los bloques del prompt del sistema desde archivos."""
        try:
            system_base = self._read_prompt_file("system.txt")
            visualizer_block = self._read_prompt_file("visualizer.txt")
            minecraft_block = self._read_prompt_file("minecraft.txt")
            
            # Construcción dinámica
            prompt = f"{system_base}\n"
            prompt += f"{visualizer_block}\n"
            prompt += f"{minecraft_block}\n"
            prompt += f"Estás hablando con {user_name}.\n"
            
            if self.modos_activos["minecraft"]:
                prompt += "[ESTADO: MODO MINECRAFT ACTIVO]"
            else:
                prompt += "[ESTADO: MODO MINECRAFT INACTIVO]"
                
            return prompt
        except Exception as e:
            log.error(f"❌ Error al construir el System Prompt dinámico: {e}")
            return "Eres Jarvis, un asistente personal."

    def _read_prompt_file(self, filename: str) -> str:
        """Método helper para leer de forma segura archivos de texto en la carpeta prompts."""
        file_path = self.prompts_dir / filename
        if file_path.exists():
            return file_path.read_text(encoding="utf-8")
        log.warning(f"⚠️ Archivo de prompt no encontrado: {filename}")
        return ""

    async def procesar_con_mcp(self, messages: list) -> str:
        """Maneja el bucle de razonamiento de herramientas con el Gateway MCP remoto."""
        try:
            async with sse_client(self.mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    mcp_tools = await session.list_tools()
                    
                    groq_tools = []
                    for t in mcp_tools.tools:
                        if t.name == "ejecutar_plan_minecraft" and not self.modos_activos["minecraft"]:
                            continue
                        groq_tools.append({
                            "type": "function",
                            "function": {
                                "name": t.name,
                                "description": t.description,
                                "parameters": t.inputSchema
                            }
                        })

                    # Loop de razonamiento (máx 5 iteraciones)
                    for intento in range(5):
                        # [EVENTO OK] Avisamos que Llama-3 está procesando/pensando
                        self.events.emit("ThinkingStarted")
                        log.info(f"🧠 Consultando a Llama-3 (iteración {intento + 1})...")
                        
                        chat_completion = self.groq_client.chat.completions.create(
                            model=self.model_name,
                            messages=messages,
                            temperature=0.7,
                            max_tokens=300,
                            tools=groq_tools if groq_tools else None
                        )

                        response_msg = chat_completion.choices[0].message
                        jarvis_texto = response_msg.content or ""

                        if not response_msg.tool_calls:
                            log.info("✅ Llama-3 terminó de razonar, sin más tool calls.")
                            break

                        messages.append({
                            "role": "assistant",
                            "content": response_msg.content,
                            "tool_calls": [tc.model_dump() for tc in response_msg.tool_calls]
                        })

                        for tool_call in response_msg.tool_calls:
                            nombre = tool_call.function.name
                            try:
                                argumentos = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                argumentos = {}
                            
                            # [EVENTO OK] Avisamos ANTES de ejecutar la acción motriz
                            self.events.emit("ToolCalled", nombre, argumentos)
                            log.info(f"⚡ Ejecutando tool: {nombre} con args: {argumentos}")
                            
                            try:
                                resultado_mcp = await session.call_tool(nombre, argumentos)
                                resultado_texto = resultado_mcp.content[0].text
                            except Exception as e:
                                resultado_texto = f"Error al ejecutar {nombre}: {str(e)}"
                            
                            # [EVENTO OK] Avisamos que la acción terminó y enviamos el resultado
                            self.events.emit("ToolFinished", nombre, resultado_texto)
                            log.info(f"📋 Resultado de {nombre}: {resultado_texto}")

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": resultado_texto
                            })
                    else:
                        jarvis_texto = "Hice varias cosas pero me perdí en el proceso, señor."

                    return jarvis_texto

        except Exception as e:
            log.error(f"[MCP ERROR] Falló la comunicación con el Gateway: {e}")
            return "Tengo un problema de conexión con mi sistema motriz, señor."

    def interactuar(self, user_id: str, user_text: str) -> str:
        """Punto de entrada síncrono para interactuar con esta instancia de Jarvis."""
        texto_limpio = user_text.lower()
        
        # 1. Interruptores de Estado Interno (Comandos rápidos del sistema)
        if "activa el modo minecraft" in texto_limpio or "conéctate a minecraft" in texto_limpio:
            self.modos_activos["minecraft"] = True
            return "Modo Minecraft activado, señor. Protocolos de supervivencia en línea."
        elif "desactiva el modo minecraft" in texto_limpio or "apaga el modo minecraft" in texto_limpio:
            self.modos_activos["minecraft"] = False
            return "Modo Minecraft desactivado. Retomando funciones estándar."

        # [EVENTO CORREGIDO] Solo se dispara si el mensaje realmente va a ser procesado por el LLM
        self.events.emit("MessageReceived", user_id, user_text)

        if user_id not in self.conversations:
            self.conversations[user_id] = []

        # 2. Inyección de Contexto Dinámico y RAG
        context = search(user_text)
        user_name = get_name(user_id)
        system_prompt = self.build_system_prompt(user_name)

        if self.modos_activos["minecraft"]:
            try:
                import requests
                estado = requests.get("http://localhost:4000/estado", timeout=3).json()
                system_prompt += f"\n\n[ESTADO MINECRAFT]\n{json.dumps(estado, ensure_ascii=False)}"
            except Exception as e:
                log.warning(f"[BRIDGE] No pude leer el estado de Minecraft: {e}")
                system_prompt += "\n[Estado de Minecraft no disponible momentáneamente]"

        if context:
            system_prompt += f"\n\n[CONOCIMIENTO EXTRA VÍA RAG]\n{context}"

        # 3. Gestión de Memoria a Corto Plazo
        self.conversations[user_id].append({"role": "user", "content": user_text})
        if len(self.conversations[user_id]) > 6:
            self.conversations[user_id] = self.conversations[user_id][-6:]

        messages = [{"role": "system", "content": system_prompt}] + self.conversations[user_id]

        # 4. Puente asíncrono (Usando la función global del archivo sin importar de sí mismo)
        jarvis_response = _ejecutar_async(self.procesar_con_mcp(messages))
        
        # [EVENTO OK] La respuesta textual está lista para ser leída/procesada por el TTS
        self.events.emit("ResponseGenerated", user_id, jarvis_response)

        self.conversations[user_id].append({"role": "assistant", "content": jarvis_response})
        return jarvis_response

# Si mantienes tu función auxiliar fuera de la clase, déjala al final del archivo:
def _ejecutar_async(coro):
    import asyncio
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    else:
        return asyncio.run(coro)