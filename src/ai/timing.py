import time
import logging
from contextlib import contextmanager

log = logging.getLogger(__name__)


class LatencyTracker:
    """
    Acumula la duración de las distintas etapas de un turno (STT, LLM, TTS,
    tools MCP, etc.) y permite loguear un resumen end-to-end al final.

    Uso:
        tracker = LatencyTracker(label="turno:usuario123")
        with tracker.stage("STT"):
            ... transcribir ...
        with tracker.stage("LLM"):
            ... llamar al agente ...
        tracker.log_summary()

    Si el mismo nombre de etapa se usa más de una vez (por ejemplo "groq_llm"
    en cada iteración del loop de tools), los tiempos se acumulan en vez de
    sobreescribirse.
    """

    def __init__(self, label: str = ""):
        self.label = label
        self.stages: dict[str, float] = {}
        self._t0 = time.perf_counter()

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.stages[name] = self.stages.get(name, 0.0) + elapsed
            log.info(f"⏱️  [{self.label}] {name}: {elapsed:.2f}s")

    def summary(self) -> str:
        total = time.perf_counter() - self._t0
        detalle = " | ".join(f"{k}={v:.2f}s" for k, v in self.stages.items())
        return f"⏱️  [{self.label}] TOTAL: {total:.2f}s  ({detalle})"

    def log_summary(self):
        log.info(self.summary())