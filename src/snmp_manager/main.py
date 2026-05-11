#!/usr/bin/env python3
"""
Gestor SNMP para cluster RoCEv2.

Pollea workers y switch vía SNMP, calcula métricas derivadas
y escribe todo a InfluxDB para visualización en Grafana.

Uso:
    python main.py
    python main.py --debug
"""

import argparse
import asyncio
import logging
import signal
import sys

from calculator import MetricsCalculator
from manager import Manager
from poller import SNMPPoller
from syslog_alert_manager import SyslogAlertManager
from writer import InfluxDBWriter
from trap_receiver import SNMPTrapReceiver


def setup_logging(debug: bool = False) -> None:
    """Configura logging con nivel y formato apropiados."""
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)-7s] %(name)-18s — %(message)s"
    datefmt = "%H:%M:%S"

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)

    # Silenciar pysnmp en modo no-debug
    if not debug:
        logging.getLogger("pysnmp").setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gestor SNMP para cluster RoCEv2"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Logging en modo DEBUG"
    )
    args = parser.parse_args()

    setup_logging(debug=args.debug)
    logger = logging.getLogger("main")

    # --- CAMBIO CLAVE: Crear y establecer el loop ANTES de iniciar pysnmp ---
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Crear componentes
    poller = SNMPPoller()
    calculator = MetricsCalculator()
    writer = InfluxDBWriter()

    # Conectar a InfluxDB
    try:
        writer.connect()
    except Exception as e:
        logger.error("No se pudo conectar a InfluxDB: %s", e)
        logger.error(
            "Verifica que InfluxDB está corriendo: "
            "sudo systemctl status influxdb"
        )
        sys.exit(1)

    # Crear manager
    mgr = Manager(poller=poller, calculator=calculator, writer=writer)

    # Configurar y arrancar el Trap Receiver (ahora se enganchará al loop correcto)
    trap_receiver = SNMPTrapReceiver(callback_func=writer.write_congestion_trap)
    try:
        trap_receiver.setup()
    except Exception as e:
        logger.error("No se pudo iniciar el servidor de Traps: %s", e)
        sys.exit(1)

    # Configurar y arrancar el manager Syslog/Snort en el mismo event loop
    syslog_alert_manager = SyslogAlertManager()
    try:
        loop.run_until_complete(syslog_alert_manager.start())
    except Exception as e:
        logger.error("No se pudo iniciar el servidor Syslog/Snort: %s", e)
        sys.exit(1)

    # Manejar Ctrl+C
    def shutdown(sig, frame):
        logger.info("Recibida señal %s — cerrando...", sig)
        mgr.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Ejecutar
    try:
        loop.run_until_complete(mgr.run())
    except KeyboardInterrupt:
        pass
    finally:
        syslog_alert_manager.close()
        writer.close()
        loop.close()
        logger.info("Gestor finalizado")


if __name__ == "__main__":
    main()
