import time
import random
import pytchat
import logging
import threading

# Importamos el cerebro de Jarvis
from src.ai.llm import get_llm_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

VIDEO_ID = "zkEQgZpPJE8"
INTERVALO_SEGUNDOS = 30  # 3 minutos (180 segundos)

# Buffer global para almacenar los mensajes del lapso actual
buffer_mensajes = []

def recolector_mensajes():
    """HILO 1 (Productor): Escucha pasivamente a YouTube y guarda todo en el buffer."""
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
                # Guardamos una tupla con (autor, mensaje)
                buffer_mensajes.append((c.author.name, c.message))
                
            time.sleep(1) # Pequeña pausa para no saturar el procesador
        except Exception as e:
            log.error(f"Error leyendo el chat: {e}")
            break

def procesador_intervalos():
    """HILO 2 (Consumidor): Despierta cada X segundos, elige un mensaje y responde."""
    global buffer_mensajes
    
    while True:
        # Jarvis duerme este proceso por 3 minutos
        time.sleep(INTERVALO_SEGUNDOS)
        
        # 1. Hacemos una copia rápida de los mensajes y vaciamos la caja original
        mensajes_disponibles = buffer_mensajes.copy()
        buffer_mensajes.clear()
        
        if not mensajes_disponibles:
            log.info("📭 Pasaron 3 minutos, pero el chat estuvo inactivo. Jarvis sigue en lo suyo...")
            continue
        
        # 2. Elegir un mensaje al azar del lapso de 3 minutos
        autor_elegido, mensaje_elegido = random.choice(mensajes_disponibles)
        log.info(f"🎯 De {len(mensajes_disponibles)} mensajes, Jarvis eligió el de {autor_elegido}: '{mensaje_elegido}'")
        
        # 3. Formatear la entrada para el LLM
        # Le decimos explícitamente a Jarvis que este mensaje viene del chat público
        entrada_formateada = f"Un espectador del stream llamado {autor_elegido} dice: {mensaje_elegido}"
        
        # 4. Procesar con el cerebro
        # [CLAVE] Usamos el mismo ID siempre para que el historial sea "El chat en general"
        log.info("🧠 Procesando respuesta...")
        respuesta = get_llm_response(user_id="chat_youtube_global", user_text=entrada_formateada)
        
        log.info(f"💬 Jarvis al chat: {respuesta}")

if __name__ == "__main__":
    print("="*50)
    print("📺 Jarvis - Módulo VTuber (Modo Intervalos)")
    print("="*50)
    
    # 1. Iniciamos el recolector en un hilo secundario (Daemon)
    # Esto asegura que si cierras el programa, este hilo muera automáticamente
    hilo_recolector = threading.Thread(target=recolector_mensajes, daemon=True)
    hilo_recolector.start()
    
    # 2. El temporizador y procesador corren en el hilo principal
    procesador_intervalos()