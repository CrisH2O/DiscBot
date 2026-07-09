import os
import json
import time
import logging
import asyncio
import threading
import concurrent.futures
from pathlib import Path
from groq import AsyncGroq
from dotenv import load_dotenv
from src.ai.events import EventEmitter
from src.ai.timing import LatencyTracker

# Importaciones de MCP
from mcp import ClientSession
from mcp.client.sse import sse_client

# Tus módulos locales
from src.ai.rag import search
from src.ai.users import get_name
from src.ai.tool_config import is_enabled

load_dotenv()
log = logging.getLogger(__name__)


class JarvisAgent:
    def __init__(self, mcp_url: str = "http://localhost:3001/sse"):
        self.mcp_url = mcp_url
        self.groq_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
        self.model_name = "llama-3.3-70b-versatile"
        self.events = EventEmitter()

        # Estado del agente encapsulado (Adiós globales)
        self.modos_activos = {
            "minecraft": False
        }
        self.conversations = {}

        # Ruta base para la carga dinámica de prompts
        self.prompts_dir = Path(__file__).parent / "prompts"

        # ─────────────────────────────────────────
        # Loop persistente dedicado a la sesión MCP.
        # Vive todo el proceso, no se crea/destruye por mensaje.
        # ─────────────────────────────────────────
        self._mcp_loop = asyncio.new_event_loop()
        self._mcp_thread = threading.Thread(target=self._run_mcp_loop, daemon=True)
        self._mcp_thread.start()

        self._mcp_session = None
        self._mcp_sse_cm = None
        self._mcp_session_cm = None
        self._mcp_tools_cache = None
        self._mcp_connect_lock = None  # se crea perezosamente DENTRO del loop

    # ─────────────────────────────────────────
    # Loop persistente
    # ─────────────────────────────────────────

    def _run_mcp_loop(self):
        asyncio.set_event_loop(self._mcp_loop)
        self._mcp_loop.run_forever()

    def _submit_to_mcp_loop(self, coro):
        """Envía una corutina al loop persistente y bloquea hasta tener el resultado."""
        future = asyncio.run_coroutine_threadsafe(coro, self._mcp_loop)
        return future.result()

    def shutdown(self):
        """Cierra la sesión MCP y detiene el loop. Llamar al apagar el proceso limpiamente."""
        try:
            self._submit_to_mcp_loop(self._close_mcp_session())
        except Exception as e:
            log.warning(f"⚠️ Error cerrando sesión MCP en shutdown: {e}")
        self._mcp_loop.call_soon_threadsafe(self._mcp_loop.stop)

    # ─────────────────────────────────────────
    # Prompts
    # ─────────────────────────────────────────

    def build_system_prompt(self, user_name: str) -> str:
        """Carga y concatena dinámicamente los bloques del prompt del sistema desde archivos."""
        try:
            system_base = self._read_prompt_file("system.txt")
            visualizer_block = self._read_prompt_file("visualizer.txt")
            minecraft_block = self._read_prompt_file("minecraft.txt")

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

    # ─────────────────────────────────────────
    # Sesión MCP persistente
    # ─────────────────────────────────────────

    async def _ensure_mcp_session(self):
        """Abre la sesión MCP si no existe todavía. Si ya está abierta, no hace nada."""
        if self._mcp_connect_lock is None:
            self._mcp_connect_lock = asyncio.Lock()

        async with self._mcp_connect_lock:
            if self._mcp_session is not None:
                return  # ya conectada

            log.info("🔌 Abriendo sesión MCP persistente...")
            self._mcp_sse_cm = sse_client(self.mcp_url)
            read, write = await self._mcp_sse_cm.__aenter__()

            self._mcp_session_cm = ClientSession(read, write)
            self._mcp_session = await self._mcp_session_cm.__aenter__()
            await self._mcp_session.initialize()
            self._mcp_tools_cache = None  # forzar refetch de tools en la nueva sesión
            log.info("✅ Sesión MCP lista.")

    async def _close_mcp_session(self):
        """Cierra una conexión (rota o al apagar) para forzar reconexión limpia la próxima vez."""
        for cm in (self._mcp_session_cm, self._mcp_sse_cm):
            if cm is not None:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
        self._mcp_session = None
        self._mcp_session_cm = None
        self._mcp_sse_cm = None
        self._mcp_tools_cache = None

    async def procesar_con_mcp(self, messages: list, tracker: LatencyTracker) -> str:
        """Maneja el bucle de razonamiento de herramientas con el Gateway MCP remoto,
        reutilizando la sesión persistente en vez de reconectar por cada mensaje.
        Cada llamada a Groq y cada tool ejecutada quedan registradas en `tracker`."""
        try:
            with tracker.stage("mcp_connect"):
                await self._ensure_mcp_session()
        except Exception as e:
            log.error(f"[MCP ERROR] No se pudo conectar al Gateway: {e}")
            return "Tengo un problema de conexión con mi sistema motriz, señor."

        try:
            # Cachear la lista de tools — ya no hace falta pedirla en cada turno
            if self._mcp_tools_cache is None:
                mcp_tools = await self._mcp_session.list_tools()
                self._mcp_tools_cache = mcp_tools.tools

            groq_tools = []
            for t in self._mcp_tools_cache:
                if t.name == "ejecutar_plan_minecraft" and not self.modos_activos["minecraft"]:
                    continue
                if not is_enabled(t.name):
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
                self.events.emit("ThinkingStarted")
                log.info(f"🧠 Consultando a Llama-3 (iteración {intento + 1})...")

                with tracker.stage("groq_llm"):
                    chat_completion = await self.groq_client.chat.completions.create(
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

                    self.events.emit("ToolCalled", nombre, argumentos)
                    log.info(f"⚡ Ejecutando tool: {nombre} con args: {argumentos}")

                    try:
                        with tracker.stage(f"tool:{nombre}"):
                            resultado_mcp = await self._mcp_session.call_tool(nombre, argumentos)
                            resultado_texto = resultado_mcp.content[0].text
                    except Exception as e:
                        resultado_texto = f"Error al ejecutar {nombre}: {str(e)}"

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
            # La sesión probablemente murió (Gateway caído, red, etc.) — la tiramos
            # para forzar una reconexión limpia en el próximo turno.
            log.warning(f"[MCP ERROR] Sesión caída ({e}), reconectando para el próximo intento...")
            await self._close_mcp_session()
            return "Tengo un problema de conexión con mi sistema motriz, señor."

    def list_available_tools(self) -> list[str]:
        """Devuelve los nombres de las tools expuestas por el Gateway MCP,
        conectando y cacheando la sesión si hace falta. Pensado para que un
        panel de control externo pueda pintar switches sin duplicar la
        lógica de conexión MCP."""
        async def _list():
            await self._ensure_mcp_session()
            if self._mcp_tools_cache is None:
                mcp_tools = await self._mcp_session.list_tools()
                self._mcp_tools_cache = mcp_tools.tools
            return [t.name for t in self._mcp_tools_cache]

        return self._submit_to_mcp_loop(_list())

    # ─────────────────────────────────────────
    # Entrada principal
    # ─────────────────────────────────────────

    def interactuar(self, user_id: str, user_text: str, tracker: LatencyTracker = None) -> str:
        """Punto de entrada síncrono para interactuar con esta instancia de Jarvis.

        `tracker` es opcional: si el caller (por ejemplo server.py) ya trae uno
        para medir todo el turno end-to-end (STT + LLM + TTS), se reutiliza y
        el desglose interno (prompt_build, groq_llm, tool:<nombre>) queda
        registrado ahí mismo. Si no se pasa uno (por ejemplo desde local.py),
        se crea uno propio solo para este turno y se loguea al final.
        """
        own_tracker = tracker is None
        if tracker is None:
            tracker = LatencyTracker(label=f"turno:{user_id}")

        texto_limpio = user_text.lower()

        # 1. Interruptores de Estado Interno (Comandos rápidos del sistema)
        if "activa el modo minecraft" in texto_limpio or "conéctate a minecraft" in texto_limpio:
            self.modos_activos["minecraft"] = True
            return "Modo Minecraft activado, señor. Protocolos de supervivencia en línea."
        elif "desactiva el modo minecraft" in texto_limpio or "apaga el modo minecraft" in texto_limpio:
            self.modos_activos["minecraft"] = False
            return "Modo Minecraft desactivado. Retomando funciones estándar."

        self.events.emit("MessageReceived", user_id, user_text)

        if user_id not in self.conversations:
            self.conversations[user_id] = []

        # 2. Inyección de Contexto Dinámico y RAG
        with tracker.stage("prompt_build"):
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

        # 4. Puente síncrono → loop persistente dedicado a MCP
        jarvis_response = self._submit_to_mcp_loop(self.procesar_con_mcp(messages, tracker))

        self.events.emit("ResponseGenerated", user_id, jarvis_response)

        self.conversations[user_id].append({"role": "assistant", "content": jarvis_response})

        if own_tracker:
            tracker.log_summary()

        return jarvis_response


# ─────────────────────────────────────────
# Singleton + wrapper de compatibilidad.
# server.py, live.py y local.py siguen importando get_llm_response
# tal cual, sin necesidad de tocarlos (salvo el `tracker=` opcional).
# ─────────────────────────────────────────

agent = JarvisAgent()


def get_llm_response(user_id: str, user_text: str, tracker: LatencyTracker = None) -> str:
    return agent.interactuar(user_id, user_text, tracker=tracker)