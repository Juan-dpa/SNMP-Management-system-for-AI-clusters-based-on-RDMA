"""
TODO: integración Telegram para alertas SOAR.

Esta clase será el punto de salida para enviar una alerta al operador y escuchar
su respuesta antes de ejecutar mitigación sobre el worker víctima.
"""

from models import SnortAlert


class TelegramAlert:
    """Stub para la futura integración Telegram + respuesta de mitigación."""

    async def send_alert(self, alert: SnortAlert) -> None:
        """TODO: enviar la alerta a Telegram con acciones de respuesta."""
        raise NotImplementedError("TODO: implementar envío de alertas por Telegram")

    async def handle_callback(self, callback_payload: object) -> None:
        """TODO: escuchar respuestas y disparar corte de tráfico si procede."""
        raise NotImplementedError("TODO: implementar callback de Telegram")
