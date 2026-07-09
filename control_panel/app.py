"""
Panel de control de Jarvis.

Arranca/detiene los distintos "modos" del proyecto (bot de Discord, live de
YouTube, servidor MCP), expone un chat directo para pruebas locales sin
lanzar ningún proceso aparte, y permite activar/desactivar tools MCP con
switches que llm.py respeta en el próximo turno.

Correr con:
    uvicorn control_panel.app:app --reload --port 8000
desde la raíz del proyecto (donde están server.py, mcp/, src/).
"""

import os
import sys
import subprocess
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
load_dotenv()


# ─────────────────────────────────────────
# Rutas — AJUSTA ESTO a tu disposición real de carpetas si difiere.
# Se asume esta estructura (la del zip que compartiste):
#
#   jarvisProject-main/
#     ├── control_panel/app.py   <- este archivo
#     ├── server.py
#     ├── mcp/index.js
#     ├── src/ai/live.py
#     └── ../jarvis-go/          <- proyecto Go del bot (AJUSTAR si tu ruta es otra)
# ─────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_DIR = Path(os.environ.get("MCP_DIR", PROJECT_ROOT / "mcp"))

# ─────────────────────────────────────────
# Bot de Discord (Go) — vive en WSL, no en Windows.
#
# Si tu bot corre dentro de WSL (porque algunas dependencias de Go no andan
# bien en Windows nativo), seteá WSL_DISTRO. En ese caso GO_BOT_DIR y
# GO_BOT_BIN deben ser rutas de LINUX (ej. "/home/tu_usuario/jarvis-go"),
# no rutas de Windows ni "\\wsl$\...".
#
# Para saber el nombre exacto de tu distro: `wsl -l -v` en PowerShell.
#
# Si en cambio compilás/corrés el bot nativamente en Windows, dejá
# WSL_DISTRO sin setear (None) y usá rutas de Windows normales.
# ─────────────────────────────────────────
WSL_DISTRO = os.environ.get("WSL_DISTRO")  # p.ej. "Ubuntu" — None si NO usás WSL
GO_BOT_DIR = os.environ.get("GO_BOT_DIR", "/home/tu_usuario/jarvis-go")
GO_BOT_BIN = os.environ.get("GO_BOT_BIN")  # ruta al binario ya compilado (opcional)


def _build_go_bot_command() -> list[str]:
    """Arma el comando para lanzar el bot, ya sea nativo en Windows o dentro de WSL."""
    cmd_dentro_de_linux = GO_BOT_BIN if GO_BOT_BIN else "go run ."

    if WSL_DISTRO:
        # wsl.exe abre una sesión de bash de login (-lc) dentro de la distro
        # indicada, hace cd a la carpeta del proyecto (en Linux) y corre el
        # comando ahí. Esto es lo que le permite usar el Go instalado en WSL,
        # no el de Windows.
        shell_cmd = f"cd '{GO_BOT_DIR}' && {cmd_dentro_de_linux}"
        return ["wsl.exe", "-d", WSL_DISTRO, "--", "bash", "-lc", shell_cmd]

    if GO_BOT_BIN:
        return [GO_BOT_BIN]
    return ["go", "run", "."]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Jarvis Control Panel")

# ─────────────────────────────────────────
# Estado de procesos gestionados
# ─────────────────────────────────────────

# Cada entrada guarda una lista de subprocess.Popen (>1 solo para "discord",
# que necesita tanto server.py como el bot de Go corriendo a la vez).
_processes: dict[str, list[subprocess.Popen]] = {
    "mcp": [],
    "youtube": [],
    "discord": [],
}


def _is_running(name: str) -> bool:
    procs = _processes.get(name, [])
    if not procs:
        return False
    # Se considera "corriendo" si TODOS sus procesos siguen vivos.
    return all(p.poll() is None for p in procs)


def _stop(name: str):
    for p in _processes.get(name, []):
        if p.poll() is None:
            p.terminate()
    _processes[name] = []


# ─────────────────────────────────────────
# Endpoints de servicios (start/stop/status)
# ─────────────────────────────────────────

@app.get("/api/status")
def status():
    return {name: _is_running(name) for name in _processes}


@app.post("/api/service/mcp/start")
def start_mcp():
    if _is_running("mcp"):
        return {"ok": True, "already_running": True}
    log.info("🔌 Arrancando servidor MCP (node index.js)...")
    proc = subprocess.Popen(
        ["node", "index.js"],
        cwd=str(MCP_DIR),
    )
    _processes["mcp"] = [proc]
    return {"ok": True}


@app.post("/api/service/mcp/stop")
def stop_mcp():
    _stop("mcp")
    return {"ok": True}


@app.post("/api/service/youtube/start")
def start_youtube():
    if _is_running("youtube"):
        return {"ok": True, "already_running": True}
    log.info("📺 Arrancando módulo de YouTube live (src.ai.live)...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.ai.live"],
        cwd=str(PROJECT_ROOT),
    )
    _processes["youtube"] = [proc]
    return {"ok": True}


@app.post("/api/service/youtube/stop")
def stop_youtube():
    _stop("youtube")
    return {"ok": True}


@app.post("/api/service/discord/start")
def start_discord():
    """El modo Discord necesita DOS procesos: el servidor gRPC/STT/TTS (server.py)
    y el bot de Go que habla con Discord. Se arrancan juntos y se paran juntos."""
    if _is_running("discord"):
        return {"ok": True, "already_running": True}

    log.info("🐍 Arrancando server.py (gRPC/STT/TTS)...")
    server_proc = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=str(PROJECT_ROOT),
    )

    log.info("🤖 Arrancando bot de Discord (Go)...")
    go_cmd = _build_go_bot_command()
    # Si corre vía wsl.exe, el `cd` ya pasa DENTRO del comando de bash — pasar
    # un cwd de Windows acá no tiene sentido (es una ruta Linux) y rompería.
    go_proc = subprocess.Popen(go_cmd, cwd=None if WSL_DISTRO else str(GO_BOT_DIR))

    _processes["discord"] = [server_proc, go_proc]
    return {"ok": True}


@app.post("/api/service/discord/stop")
def stop_discord():
    _stop("discord")
    return {"ok": True}


# ─────────────────────────────────────────
# Chat directo — "Prueba local" sin lanzar ningún proceso.
# Reusa el mismo singleton `agent` que usan server.py y live.py.
# ─────────────────────────────────────────

class ChatRequest(BaseModel):
    user_id: str = "panel_local_test"
    text: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    from src.ai.llm import get_llm_response  # import perezoso: server.py y live.py
                                              # ya arrancan su propio agente si
                                              # se importa al levantar el panel
    try:
        respuesta = get_llm_response(req.user_id, req.text)
        return {"ok": True, "response": respuesta}
    except Exception as e:
        log.error(f"❌ Error en /api/chat: {e}")
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────
# Tools MCP — listar y togglear
# ─────────────────────────────────────────

@app.get("/api/tools")
def list_tools():
    from src.ai.llm import agent
    from src.ai.tool_config import is_enabled

    try:
        nombres = agent.list_available_tools()
    except Exception as e:
        return {"ok": False, "error": f"No se pudo conectar al Gateway MCP: {e}"}

    return {
        "ok": True,
        "tools": [{"name": n, "enabled": is_enabled(n)} for n in nombres],
    }


class ToolToggleRequest(BaseModel):
    enabled: bool


@app.post("/api/tools/{tool_name}/toggle")
def toggle_tool(tool_name: str, req: ToolToggleRequest):
    from src.ai.tool_config import set_enabled
    set_enabled(tool_name, req.enabled)
    log.info(f"🔧 Tool '{tool_name}' → {'habilitada' if req.enabled else 'deshabilitada'}")
    return {"ok": True}


# ─────────────────────────────────────────
# Frontend estático
# ─────────────────────────────────────────

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))