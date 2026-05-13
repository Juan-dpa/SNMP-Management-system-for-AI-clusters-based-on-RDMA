"""
SyslogAlertManager: fachada para el pipeline de alertas Snort por Syslog.

Oculta al main la recepción UDP, el throttling y el logging de alertas.
"""

import logging
import time
import asyncio

from config import SNORT_ALERT_COOLDOWN_SECONDS
from models import SnortAlert
from syslog_receiver import SyslogReceiver
from telegram_alert import TelegramAlert

logger = logging.getLogger(__name__)

UNKNOWN_FIELD = "unknown"
MISSING_PORT = "-"


class SyslogAlertManager:
    """Gestiona el ciclo de vida y la política de alertas Syslog/Snort."""

    def __init__(self, cooldown_seconds: int = SNORT_ALERT_COOLDOWN_SECONDS):
        self._cooldown_seconds = cooldown_seconds
        self._cooldowns: dict[str, float] = {}
        self._receiver = SyslogReceiver(callback_func=self._handle_alert)
        self._telegram = TelegramAlert()
 
    async def start(self) -> None:
        """Arranca el receptor Syslog y la escucha de Telegram."""
        # Creamos la tarea de Telegram en segundo plano
        asyncio.create_task(self._telegram.start_polling())
        
        # Arrancamos Syslog
        await self._receiver.start()

    def close(self) -> None:
        """Cierra el receptor Syslog asociado al manager."""
        self._receiver.close()


    def _handle_alert(self, alert: SnortAlert) -> None:
        # --- WHITELIST: Ignorar tráfico legítimo de nuestro propio Gestor ---
        if alert.source_ip == "10.10.0.254" and alert.victim_port == 161:
            return
        # --------------------------------------------------------------------

        now = time.time()
        last_seen = self._cooldowns.get(alert.victim_ip)
        """Procesa alertas Snort con throttling temporal por IP víctima."""
        now = time.time()
        last_seen = self._cooldowns.get(alert.victim_ip)

        if last_seen is not None and now - last_seen < self._cooldown_seconds:
            remaining = self._cooldown_seconds - (now - last_seen)
            logger.debug(
                "Alerta Snort suprimida por cooldown: victim=%s "
                "attack=%s remaining=%.0fs",
                alert.victim_ip,
                alert.attack_type,
                remaining,
            )
            return

        self._cooldowns[alert.victim_ip] = now
        logger.warning(
            "Alerta Snort recibida: attack=%s signature=%s protocol=%s "
            "source=%s:%s victim=%s:%s worker=%s ovs_port=%s",
            alert.attack_type,
            alert.signature_id or UNKNOWN_FIELD,
            alert.protocol or UNKNOWN_FIELD,
            alert.source_ip,
            alert.source_port if alert.source_port is not None else MISSING_PORT,
            alert.victim_ip,
            alert.victim_port if alert.victim_port is not None else MISSING_PORT,
            alert.victim_worker or UNKNOWN_FIELD,
            (
                alert.victim_ovs_port
                if alert.victim_ovs_port is not None
                else MISSING_PORT
            ),
        )
        # Enviar alerta a Telegram de forma asíncrona
        asyncio.create_task(self._telegram.send_alert(alert))
