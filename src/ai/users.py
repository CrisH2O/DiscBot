"""
Módulo de mapeo Discord user_id → nombre."""

import csv
import logging
from pathlib import Path

log = logging.getLogger(__name__)

USERS_FILE = Path(__file__).parent / "users.csv"

def get_name(user_id: str) -> str:
    """Retorna el nombre del usuario o su ID si no está registrado."""
    if not USERS_FILE.exists():
        return user_id

    try:
        with open(USERS_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["id"].strip() == user_id.strip():
                    return row["name"].strip()
    except Exception as e:
        log.warning(f"⚠️  Error leyendo users.csv: {e}")

    return user_id