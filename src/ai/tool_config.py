"""
Config compartida: qué tools MCP están habilitadas.
La lee llm.py en cada turno (para decidir qué tools ofrecer a Groq) y la
escribe el panel de control cuando el usuario togglea un switch.
Un archivo JSON simple es suficiente — no hay volumen ni concurrencia real.
"""

import json
import threading
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "tool_config.json"
_lock = threading.Lock()


def load() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with _lock:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}


def save(config: dict):
    with _lock:
        CONFIG_PATH.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def is_enabled(tool_name: str, default: bool = True) -> bool:
    """Por defecto una tool está habilitada si nunca se tocó su switch."""
    return load().get(tool_name, default)


def set_enabled(tool_name: str, enabled: bool):
    config = load()
    config[tool_name] = enabled
    save(config)