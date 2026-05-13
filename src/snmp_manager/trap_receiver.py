"""
SNMPTrapReceiver: Escucha pasiva de Traps asíncronos.

Levanta un servidor UDP para recibir notificaciones SNMP,
decodifica los varBinds y ejecuta un callback con un DTO.
"""

import logging
import time
import asyncio

from telegram_alert import TelegramAlert
from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import ntfrcv

from config import (
    IP_TO_WORKER,
    SNMP_COMMUNITY,
    SNMP_TRAP_PORT,
    TRAP_OID_CONGESTION,
    TRAP_OID_MESSAGE,
    WORKER_OIDS,
)
from models import WorkerCongestionTrap

logger = logging.getLogger(__name__)


class SNMPTrapReceiver:
    """Receptor asíncrono de Traps SNMPv2c."""

    def __init__(self, callback_func):
        self._engine = engine.SnmpEngine()
        self._callback = callback_func
        self._telegram = TelegramAlert()

    def setup(self) -> None:
        """Configura el transporte UDP y los callbacks en pysnmp."""
        # 1. Configurar transporte (escucha en todas las interfaces)
        config.addTransport(
            self._engine,
            udp.domainName + (1,),
            udp.UdpTransport().openServerMode(("0.0.0.0", SNMP_TRAP_PORT)),
        )

        # 2. Configurar la comunidad SNMP
        config.addV1System(self._engine, "my-area", SNMP_COMMUNITY)

        # 3. Registrar el callback interno de pysnmp para Traps
        ntfrcv.NotificationReceiver(self._engine, self._process_trap)
        
        logger.info("Escuchando Traps SNMP en 0.0.0.0:%s", SNMP_TRAP_PORT)

    def _process_trap(
        self, snmpEngine, stateReference, contextEngineId, contextName, varBinds, cbCtx
    ) -> None:
        """Callback interno que ejecuta pysnmp al recibir un Trap."""
        
        logger.warning(">>> ALERTA: PySNMP ha interceptado un paquete UDP <<<")

        # --- FIX API PySNMP 7.x: get_transport_info ---
        # (Dependiendo de la subversión exacta de 7.x, msgAndPduDsp también puede ser msg_and_pdu_dispatcher, 
        # pero mantenemos msgAndPduDsp porque el traceback indica que ese objeto sí existe)
        transportDomain, transportAddress = snmpEngine.msgAndPduDsp.get_transport_info(
            stateReference
        )
        source_ip = transportAddress[0]
        worker_id = IP_TO_WORKER.get(source_ip, "unknown")

        # --- FIX API PySNMP 7.x: pretty_print() en lugar de prettyPrint() ---
        var_dict = {}
        for oid, val in varBinds:
            # Manejar compatibilidad hacia atrás por si tu versión específica usa uno u otro
            val_str = val.pretty_print() if hasattr(val, "pretty_print") else val.prettyPrint()
            var_dict[str(oid)] = val_str

        logger.warning("DICCIONARIO CRUDO RECIBIDO: %s", var_dict)

        snmp_trap_oid = var_dict.get("1.3.6.1.6.3.1.1.4.1.0")
        
        if snmp_trap_oid and TRAP_OID_CONGESTION in str(snmp_trap_oid):
            in_ce_str = var_dict.get(WORKER_OIDS["in_ce_pkts"], "0")
            description = var_dict.get(TRAP_OID_MESSAGE, "Congestión detectada")

            trap_data = WorkerCongestionTrap(
                timestamp=time.time(),
                worker_id=worker_id,
                in_ce_pkts=int(in_ce_str),
                description=description,
            )

            logger.warning(
                "¡Trap de Congestión procesado! [%s] IP: %s - %s", 
                worker_id, source_ip, description
            )
            # Lanza la alerta de Telegram de forma asíncrona (fire-and-forget)
            asyncio.create_task(self._telegram.send_trap_alert(trap_data.worker_id, source_ip, str(trap_data.in_ce_pkts)))
            self._callback(trap_data)
        else:
            logger.error(
                "Trap recibido pero descartado. OID esperado: %s | OID recibido: %s",
                TRAP_OID_CONGESTION, snmp_trap_oid
            )
