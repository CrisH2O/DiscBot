import requests
import logging
log = logging.getLogger(__name__)

def obtener_estado() -> dict:
    try:
        res = requests.get(
            "http://172.27.80.1:4000/estado",
            timeout=1
        )

        if res.status_code == 200:
            return res.json()

    except Exception:
        pass

    return {
        "estado": "Desconectado del plano físico."
    }


def enviar_orden(accion_json: dict):
    try:
        requests.post(
            "http://172.27.80.1:4000/ejecutar",
            json=accion_json,
            timeout=1
        )

    except Exception as e:
        log.error(f"[MC ERROR]: {e}")

def limpiar_ultimo_plan():
    try:
        requests.post(f"http://172.27.80.1:4000/limpiar_plan", timeout=2)
    except Exception as e:
        log.error(f"[BRIDGE ERROR] limpiar_plan: {e}")