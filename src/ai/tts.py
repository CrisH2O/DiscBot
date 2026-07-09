import logging
import os
import threading
from pathlib import Path

import numpy as np
from huggingface_hub import login
from pocket_tts import TTSModel
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────

VOICE_EMBEDDING_PATH = Path(__file__).parent / "modelo" / "voz2.safetensors"
LANGUAGE = "spanish_24l"  # ajusta si tu voz/idioma es distinto

# ─────────────────────────────────────────
# Autenticación con HuggingFace (una sola vez, no interactiva)
# Necesario porque el modelo base con voice cloning de Pocket TTS
# está en un repo "gated". Usa una variable de entorno en producción,
# NO pidas login() interactivo en un servicio corriendo en background.
# ─────────────────────────────────────────

_hf_token = os.environ.get("HF_TOKEN")
if _hf_token:
    login(token=_hf_token)
else:
    log.warning(
        "⚠️  No se encontró HF_TOKEN en el entorno. Si el modelo no está "
        "cacheado localmente, la carga fallará (repo gated)."
    )

# ─────────────────────────────────────────
# Carga del modelo (una sola vez al importar)
# ─────────────────────────────────────────

log.info("⏳ Cargando modelo Pocket TTS...")
_model = TTSModel.load_model(language=LANGUAGE)
_voice_state = _model.get_state_for_audio_prompt(str(VOICE_EMBEDDING_PATH))
SAMPLE_RATE = _model.sample_rate
log.info(f"✅ Pocket TTS listo (sample_rate={SAMPLE_RATE}Hz).")

# Pocket TTS (como la mayoría de modelos de inferencia en PyTorch) no está
# garantizado como thread-safe para llamadas concurrentes de generate_audio
# sobre la misma instancia. Si tu bot puede procesar TTS de varios canales de
# voz al mismo tiempo, protege las llamadas con este lock.
_inference_lock = threading.Lock()


# ─────────────────────────────────────────
# Efectos
# ─────────────────────────────────────────
# NOTA: el pitch-shift y el filtrado paso-alto/paso-bajo tenían sentido con
# Piper porque ahí controlabas el timbre "crudo" del modelo genérico.
# Con voice cloning, el timbre ya viene definido por tu audio de referencia
# (diseñado con Qwen3-TTS), así que aplicar pitch-shift adicional puede sonar
# artificial o desalinear el timbre elegido. Se deja el compresor porque sigue
# siendo útil para nivelar volumen antes de mandar a Discord.

def _compressor(audio: np.ndarray, threshold: float = 0.3, ratio: float = 2.5) -> np.ndarray:
    compressed = np.copy(audio)
    mask = np.abs(audio) > threshold
    compressed[mask] = np.sign(audio[mask]) * (
        threshold + (np.abs(audio[mask]) - threshold) / ratio
    )
    peak = np.max(np.abs(compressed))
    if peak > 0:
        compressed = compressed / peak * 0.9
    return compressed


def _apply_effects(audio: np.ndarray, sr: int) -> np.ndarray:
    audio = _compressor(audio, threshold=0.3, ratio=2.5)
    return audio


# ─────────────────────────────────────────
# Funciones internas
# ─────────────────────────────────────────

def _synthesize_to_numpy(text: str) -> np.ndarray:
    with _inference_lock:
        audio_tensor = _model.generate_audio(_voice_state, text)

    audio = audio_tensor.detach().cpu().numpy()
    if audio.ndim > 1:
        # generate_audio puede devolver (1, n_samples) o (canales, n_samples);
        # nos quedamos con un solo canal (mono) antes de mandarlo a Go.
        audio = audio.squeeze()
        if audio.ndim > 1:
            audio = audio[0]

    return audio.astype(np.float32)


def _float32_to_pcm16(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767).astype(np.int16).tobytes()


# ─────────────────────────────────────────
# Función principal
# ─────────────────────────────────────────

def synthesize(text: str) -> bytes:
    if not text.strip():
        return b""

    try:
        audio = _synthesize_to_numpy(text)
        audio_fx = _apply_effects(audio, SAMPLE_RATE)
        pcm = _float32_to_pcm16(audio_fx)

        log.info(f"🔊 TTS generado: {len(pcm)} bytes PCM ({len(pcm)/2/SAMPLE_RATE:.2f}s)")
        return pcm

    except Exception as e:
        log.error(f"❌ Error en TTS: {e}")
        return b""