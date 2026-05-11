"""
SyslogReceiver: escucha alertas de Snort reenviadas por rsyslog.

El flujo esperado es UDP crudo -> Python. No convierte alertas a SNMP.
"""

import asyncio
import inspect
import logging
import re
import time
from collections.abc import Callable

from config import (
    IP_TO_WORKER,
    IP_TO_WORKER_OVS_PORT,
    SYSLOG_LISTEN_HOST,
    SYSLOG_LISTEN_PORT,
)
from models import SnortAlert

logger = logging.getLogger(__name__)

SNORT_PROGRAM_MARKER = "snort"
UNKNOWN_ATTACK_TYPE = "unknown"

_FLOW_RE = re.compile(
    r"(?P<src_ip>\d{1,3}(?:\.\d{1,3}){3})"
    r"(?::(?P<src_port>\d+))?\s*->\s*"
    r"(?P<dst_ip>\d{1,3}(?:\.\d{1,3}){3})"
    r"(?::(?P<dst_port>\d+))?"
)
_SIGNATURE_RE = re.compile(
    r"\[(?P<signature_id>\d+:\d+:\d+)\]\s*(?P<attack_type>.+?)(?:\s*\{|$)"
)
_PROTOCOL_RE = re.compile(r"\{(?P<protocol>[A-Z0-9]+)\}")


class SyslogReceiver(asyncio.DatagramProtocol):
    """Receptor UDP asíncrono para alertas Syslog generadas por Snort."""

    def __init__(
        self,
        callback_func: Callable[[SnortAlert], object],
        host: str = SYSLOG_LISTEN_HOST,
        port: int = SYSLOG_LISTEN_PORT,
    ):
        self._callback = callback_func
        self._host = host
        self._port = port
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        """Levanta el endpoint UDP en el event loop activo."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=(self._host, self._port),
        )
        self._transport = transport
        logger.info("Escuchando Syslog/Snort en %s:%s", self._host, self._port)

    def close(self) -> None:
        """Cierra el transporte UDP si está activo."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def datagram_received(self, data: bytes, addr) -> None:
        """Procesa un datagrama Syslog sin bloquear el event loop."""
        message = data.decode("utf-8", errors="replace").strip()

        if SNORT_PROGRAM_MARKER not in message.lower():
            logger.debug("Syslog no-Snort descartado desde %s: %s", addr, message)
            return

        alert = self._parse_message(message)
        if alert is None:
            logger.warning("Alerta Snort no parseable desde %s: %s", addr, message)
            return

        try:
            result = self._callback(alert)
            if inspect.isawaitable(result):
                asyncio.create_task(result)
        except Exception as e:
            logger.error("Error procesando alerta Snort: %s", e)

    def _parse_message(self, message: str) -> SnortAlert | None:
        """Extrae los campos principales de una alerta Snort en formato Syslog."""
        flow_match = _FLOW_RE.search(message)
        if flow_match is None:
            return None

        signature_match = _SIGNATURE_RE.search(message)
        protocol_match = _PROTOCOL_RE.search(message)

        victim_ip = flow_match.group("dst_ip")
        victim_worker = IP_TO_WORKER.get(victim_ip)
        attack_type = UNKNOWN_ATTACK_TYPE
        signature_id = None

        if signature_match is not None:
            signature_id = signature_match.group("signature_id")
            attack_type = signature_match.group("attack_type").strip()

        return SnortAlert(
            timestamp=time.time(),
            raw_message=message,
            signature_id=signature_id,
            attack_type=attack_type,
            protocol=protocol_match.group("protocol") if protocol_match else None,
            source_ip=flow_match.group("src_ip"),
            source_port=self._parse_port(flow_match.group("src_port")),
            victim_ip=victim_ip,
            victim_port=self._parse_port(flow_match.group("dst_port")),
            victim_worker=victim_worker,
            victim_ovs_port=IP_TO_WORKER_OVS_PORT.get(victim_ip),
        )

    @staticmethod
    def _parse_port(value: str | None) -> int | None:
        if value is None:
            return None
        return int(value)
