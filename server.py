import grpc
import io
import logging
import tempfile
import os
from concurrent import futures
import json

import audio_bridge_pb2
import audio_bridge_pb2_grpc
from faster_whisper import WhisperModel
from tts import synthesize
from llm import get_llm_response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────

MODEL_SIZE  = "turbo"
LANGUAGE    = "es"
DEVICE      = "cuda"
COMPUTE     = "float16"
GRPC_PORT   = "50051"

# ─────────────────────────────────────────
# Palabras clave de activación
# ─────────────────────────────────────────

WAKE_WORDS = [
    "jarvis", "oye jarvis", "hey jarvis", "hervis", "jervis",
    "xarvis", "yarvis", "yervis", "harvis", "herbis", "herviz",
    "hervys", "hervus", "javis",
]

def contains_wake_word(text: str) -> bool:
    text_lower = text.lower()
    return any(word in text_lower for word in WAKE_WORDS)

# ─────────────────────────────────────────
# Servicio gRPC
# ─────────────────────────────────────────

class AudioServiceServicer(audio_bridge_pb2_grpc.AudioServiceServicer):

    def __init__(self, model: WhisperModel):
        self.model = model

    def StreamAudio(self, request_iterator, context):
        audio_buffer = io.BytesIO()
        user_id = None

        for chunk in request_iterator:
            if user_id is None:
                user_id = chunk.user_id
            audio_buffer.write(chunk.data)

        audio_buffer.seek(0)
        total_bytes = audio_buffer.getbuffer().nbytes
        log.info(f"📥 Audio recibido — Usuario: {user_id}, Bytes: {total_bytes}")

        if total_bytes == 0:
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_buffer.read())
            tmp_path = tmp.name

        try:
            # 1. Transcribir
            segments, _ = self.model.transcribe(
                tmp_path,
                language=LANGUAGE,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
            )

            transcript = " ".join(s.text.strip() for s in segments).strip()

            if not transcript:
                log.info("🔇 Sin voz detectada.")
                return

            if not contains_wake_word(transcript):
                log.info(f"💤 Sin palabra clave — ignorando: {transcript}")
                return

            log.info(f"🎤 [{user_id}]: {transcript}")

            # 2. LLM + RAG
            log.info("🤖 Consultando LLM...")
            response = get_llm_response(user_id, transcript)
            log.info(f"💬 Jarvis: {response}")

            # 3. TTS
            log.info("🔊 Sintetizando voz con Piper...")
            audio_pcm = synthesize(response)

            if not audio_pcm:
                log.warning("⚠️  TTS no produjo audio, enviando solo texto.")

            # 4. Devolver texto + audio PCM a Go
            yield audio_bridge_pb2.TranscriptionResult(
                text=response,
                user_id=user_id,
                audio=audio_pcm,
            )

        except Exception as e:
            log.error(f"❌ Error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))

        finally:
            os.unlink(tmp_path)

# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def serve():
    log.info(f"⏳ Cargando modelo Whisper '{MODEL_SIZE}' en {DEVICE}...")
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE)
    log.info("✅ Modelo listo.")

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    audio_bridge_pb2_grpc.add_AudioServiceServicer_to_server(
        AudioServiceServicer(model), server
    )

    server.add_insecure_port(f"[::]:{GRPC_PORT}")
    server.start()
    log.info(f"🚀 Servidor gRPC escuchando en puerto {GRPC_PORT}")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        log.info("🛑 Servidor detenido.")
        server.stop(0)

if __name__ == "__main__":
    serve()