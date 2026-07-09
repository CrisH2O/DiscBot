class EventEmitter:
    def __init__(self):
        self._listeners = {}

    def on(self, event_name: str, callback: callable):
        """Suscribe una función a un evento específico."""
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        self._listeners[event_name].append(callback)

    def emit(self, event_name: str, *args, **kwargs):
        """Dispara un evento, llamando a todas las funciones suscritas."""
        for callback in self._listeners.get(event_name, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error en listener del evento {event_name}: {e}")