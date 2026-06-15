import io
import logging
import wave
from pathlib import Path

import numpy as np
import pyrubberband
from scipy import signal
from piper.voice import PiperVoice

log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Configuración
# ─────────────────────────────────────────

MODEL_PATH  = Path(__file__).parent / "modelo" / "es_MX-claude-high.onnx"
CONFIG_PATH = Path(__file__).parent / "modelo" / "es_MX-claude-high.onnx.json"
SAMPLE_RATE = 22050

PITCH_SEMITONES = 2.0   # ajusta al gusto

# ─────────────────────────────────────────
# Carga del modelo (una sola vez al importar)
# ─────────────────────────────────────────

log.info("⏳ Cargando modelo Piper...")
_voice = PiperVoice.load(str(MODEL_PATH), config_path=str(CONFIG_PATH), use_cuda=False)
log.info("✅ Piper listo.")


# ─────────────────────────────────────────
# Efectos
# ─────────────────────────────────────────

def _highpass(audio: np.ndarray, cutoff: float, sr: int) -> np.ndarray:
    sos = signal.butter(4, cutoff, btype="high", fs=sr, output="sos")
    return signal.sosfilt(sos, audio)

def _lowpass(audio: np.ndarray, cutoff: float, sr: int) -> np.ndarray:
    sos = signal.butter(4, cutoff, btype="low", fs=sr, output="sos")
    return signal.sosfilt(sos, audio)

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
    audio = pyrubberband.pitch_shift(audio, sr, PITCH_SEMITONES)
    audio = _compressor(audio, threshold=0.3, ratio=2.5)
    return audio


# ─────────────────────────────────────────
# Funciones internas
# ─────────────────────────────────────────

def _synthesize_to_numpy(text: str) -> np.ndarray:
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        _voice.synthesize_wav(text, wav_file)

    wav_buffer.seek(0)
    with wave.open(wav_buffer, "rb") as wav_file:
        pcm_bytes = wav_file.readframes(wav_file.getnframes())

    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    return audio_int16.astype(np.float32) / 32768.0

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