import time
import random
import pytchat
import logging
import threading
import queue

# Importamos el cerebro de Jarvis
from src.ai.llm import get_llm_response
from src.ai.timing import LatencyTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

VIDEO_ID = "zkEQgZpPJE8"
INTERVALO_SEGUNDOS = 30  # 3 minutos (180 segundos)

# Cola thread-safe para los mensajes del chat. Reemplaza a la lista global +
# copy()/clear(), que tenía una condición de carrera: un mensaje podía llegar
# entre el copy() y el clear() y se perdía sin ser procesado.
buffer_mensajes: "queue.Queue[tuple[str, str]]" = queue.Queue()


def recolector_mensajes():
    """HILO 1 (Productor): Escucha pasivamente a YouTube y guarda todo en la cola."""
    log.info(f"⏳ Conectando al chat en vivo de YouTube (ID: {VIDEO_ID})...")
    chat = pytchat.create(video_id=VIDEO_ID, interruptable=False)

    if chat.is_alive():
        log.info("✅ Conectado al chat de YouTube. Recolectando mensajes en silencio...")
    else:
        log.error("❌ No se pudo conectar. Verifica que el ID del video sea correcto y esté en vivo.")
        return

    while chat.is_alive():
        try:
            for c in chat.get().sync_items():
                # put() es atómico e hilo-seguro, a diferencia de list.append()
                # combinado con el copy()/clear() que hacía el consumidor.
                buffer_mensajes.put((c.author.name, c.message))

            time.sleep(1)  # Pequeña pausa para no saturar el procesador
        except Exception as e:
            log.error(f"Error leyendo el chat: {e}")
            break


def procesador_intervalos():
    """HILO 2 (Consumidor): Despierta cada X segundos, elige un mensaje y responde."""
    while True:
        # Jarvis duerme este proceso por el intervalo configurado
        time.sleep(INTERVALO_SEGUNDOS)

        # 1. Vaciar la cola de forma segura — get_nowait() no compite con el
        #    productor de la forma en que competía copy()+clear() sobre una lista.
        mensajes_disponibles = []
        while True:
            try:
                mensajes_disponibles.append(buffer_mensajes.get_nowait())
            except queue.Empty:
                break

        if not mensajes_disponibles:
            log.info("📭 Pasó el intervalo, pero el chat estuvo inactivo. Jarvis sigue en lo suyo...")
            continue

        # 2. Elegir un mensaje al azar del lapso transcurrido
        autor_elegido, mensaje_elegido = random.choice(mensajes_disponibles)
        log.info(f"🎯 De {len(mensajes_disponibles)} mensajes, Jarvis eligió el de {autor_elegido}: '{mensaje_elegido}'")

        # 3. Formatear la entrada para el LLM
        entrada_formateada = f"Un espectador del stream llamado {autor_elegido} dice: {mensaje_elegido}"

        # 4. Procesar con el cerebro, midiendo cuánto tarda el turno completo
        tracker = LatencyTracker(label="live_chat")
        log.info("🧠 Procesando respuesta...")
        with tracker.stage("LLM"):
            respuesta = get_llm_response(
                user_id="chat_youtube_global",
                user_text=entrada_formateada,
                tracker=tracker,
            )
        tracker.log_summary()

        log.info(f"💬 Jarvis al chat: {respuesta}")


if __name__ == "__main__":
    print("=" * 50)
    print("📺 Jarvis - Módulo VTuber (Modo Intervalos)")
    print("=" * 50)

    # 1. Iniciamos el recolector en un hilo secundario (Daemon)
    hilo_recolector = threading.Thread(target=recolector_mensajes, daemon=True)
    hilo_recolector.start()

    # 2. El temporizador y procesador corren en el hilo principal
    procesador_intervalos()