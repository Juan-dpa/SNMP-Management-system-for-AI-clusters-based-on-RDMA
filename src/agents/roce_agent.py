#!/usr/bin/env python3
"""
Agente SNMP pass_persist para workers Soft-RoCE.

Expone dos tablas bajo .1.3.6.1.4.1.99999:
  .1.3.6.1.4.1.99999.1.X.0  -> rocePortTable  (contadores RDMA)
  .1.3.6.1.4.1.99999.2.X.0  -> roceEcnTable   (contadores ECN)

Evalúa la métrica InCEPkts (Congestion Experienced) y envía un TRAP 
automático si detecta un incremento (delta) >= 34 en el intervalo.
"""

import sys
import os
import subprocess
import time

BASE_OID = ".1.3.6.1.4.1.99999"
RXE_DEVICE = "rxe0"
RXE_PORT = "1"

# --- Configuración de Traps ---
TRAP_DEST = "10.10.0.254:1162"
TRAP_COMMUNITY = "public"
TRAP_OID = f"{BASE_OID}.0.1"  # OID genérico para identificar este trap específico
CHECK_INTERVAL = 10           # Segundos mínimos entre evaluaciones de deltas para evitar spam en snmpwalks
CE_TRAP_THRESHOLD = 34        # Umbral de tolerancia de paquetes CE por intervalo

# --- Variables de estado global para Deltas ---
last_ecn_values = {}
last_check_time = 0

# --- Definición de OIDs ---
HW_COUNTERS_DIR = f"/sys/class/infiniband/{RXE_DEVICE}/ports/{RXE_PORT}/hw_counters"

ROCE_PORT_TABLE = [
    ("1.1.0",  "counter64", "sent_pkts",              HW_COUNTERS_DIR),
    ("1.2.0",  "counter64", "rcvd_pkts",              HW_COUNTERS_DIR),
    ("1.3.0",  "counter64", "rdma_sends",             HW_COUNTERS_DIR),
    ("1.4.0",  "counter64", "rdma_recvs",             HW_COUNTERS_DIR),
    ("1.5.0",  "counter64", "rcvd_seq_err",           HW_COUNTERS_DIR),
    ("1.6.0",  "counter64", "retry_exceeded_err",     HW_COUNTERS_DIR),
    ("1.7.0",  "counter64", "rcvd_rnr_err",           HW_COUNTERS_DIR),
    ("1.8.0",  "counter64", "send_rnr_err",           HW_COUNTERS_DIR),
    ("1.9.0",  "counter64", "duplicate_request",      HW_COUNTERS_DIR),
    ("1.10.0", "counter64", "out_of_seq_request",     HW_COUNTERS_DIR),
    ("1.11.0", "counter64", "completer_retry_err",    HW_COUNTERS_DIR),
    ("1.12.0", "counter64", "ack_deferred",           HW_COUNTERS_DIR),
    ("1.13.0", "counter64", "send_err",               HW_COUNTERS_DIR),
    ("1.14.0", "counter64", "retry_rnr_exceeded_err", HW_COUNTERS_DIR),
    ("1.15.0", "counter64", "link_downed",            HW_COUNTERS_DIR),
    ("1.16.0", "integer",   "lifespan",               HW_COUNTERS_DIR),
]

ECN_FIELDS = [
    ("2.1.0", "InCEPkts"),
    ("2.2.0", "InECT0Pkts"),
    ("2.3.0", "InECT1Pkts"),
    ("2.4.0", "InNoECTPkts"),
]


def send_trap(field_name, oid_afectado, delta):
    """Ejecuta snmptrap en un subproceso para enviar la alerta."""
    cmd = [
        "snmptrap", "-v2c", "-c", TRAP_COMMUNITY, TRAP_DEST,
        "", TRAP_OID,
        oid_afectado, "c", str(delta),
        f"{BASE_OID}.0.2", "s", f"Alta congestion ECN detectada: {delta} {field_name} en {CHECK_INTERVAL}s"
    ]
    try:
        # Usamos stdout/stderr DEVNULL para no interferir con la comunicación stdin/stdout de pass_persist
        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def evaluate_ecn_deltas(current_ecn_data):
    """Calcula deltas y dispara traps si hay incrementos que superen el umbral."""
    global last_ecn_values, last_check_time
    
    current_time = time.time()
    
    # Prevenir que lecturas masivas saturen el sistema o pisen el baseline
    if current_time - last_check_time < CHECK_INTERVAL:
        return

    # Si es la primera ejecución, solo inicializamos la línea base
    if not last_ecn_values:
        last_ecn_values = current_ecn_data.copy()
        last_check_time = current_time
        return

    # Solo evaluamos InCEPkts (OID 2.1.0)
    field_name = "InCEPkts"
    sub_oid = "2.1.0"
    
    current_val = current_ecn_data.get(field_name, 0)
    last_val = last_ecn_values.get(field_name, 0)
    
    delta = current_val - last_val
    if delta >= CE_TRAP_THRESHOLD:
        full_oid = f"{BASE_OID}.{sub_oid}"
        send_trap(field_name, full_oid, delta)

    # Actualizamos el estado para la próxima evaluación (guardamos todas las métricas)
    last_ecn_values = current_ecn_data.copy()
    last_check_time = current_time


def read_sysfs(directory, filename):
    path = os.path.join(directory, filename)
    try:
        with open(path, "r") as f:
            return int(f.read().strip())
    except (IOError, ValueError):
        return 0


def read_ecn_counters():
    result = {}
    try:
        with open("/proc/net/netstat", "r") as f:
            lines = f.readlines()

        keys = None
        vals = None
        for i, line in enumerate(lines):
            if line.startswith("IpExt:") and keys is None:
                keys = line.strip().split()
                if i + 1 < len(lines):
                    vals = lines[i + 1].strip().split()
                break

        if keys and vals and len(keys) == len(vals):
            field_map = dict(zip(keys, vals))
            for _, field_name in ECN_FIELDS:
                result[field_name] = int(field_map.get(field_name, "0"))
    except (IOError, ValueError):
        pass

    return result


def build_oid_map():
    oid_map = {}

    # rocePortTable
    for sub_oid, snmp_type, filename, directory in ROCE_PORT_TABLE:
        full_oid = f"{BASE_OID}.{sub_oid}"
        value = read_sysfs(directory, filename)
        oid_map[full_oid] = (snmp_type, str(value))

    # roceEcnTable
    ecn_data = read_ecn_counters()
    
    # Inyectar aquí la evaluación de traps antes de rellenar el mapa
    evaluate_ecn_deltas(ecn_data)
    
    for sub_oid, field_name in ECN_FIELDS:
        full_oid = f"{BASE_OID}.{sub_oid}"
        value = ecn_data.get(field_name, 0)
        oid_map[full_oid] = ("counter64", str(value))

    return oid_map


def oid_sort_key(oid_str):
    return [int(x) for x in oid_str.strip(".").split(".")]


def handle_get(oid):
    oid_map = build_oid_map()
    if oid in oid_map:
        snmp_type, value = oid_map[oid]
        print(oid)
        print(snmp_type)
        print(value)
    else:
        print("NONE")


def handle_getnext(oid):
    oid_map = build_oid_map()
    sorted_oids = sorted(oid_map.keys(), key=oid_sort_key)

    for candidate in sorted_oids:
        if oid_sort_key(candidate) > oid_sort_key(oid):
            snmp_type, value = oid_map[candidate]
            print(candidate)
            print(snmp_type)
            print(value)
            return

    print("NONE")


def main():
    sys.stdout = os.fdopen(sys.stdout.fileno(), "w", buffering=1)

    while True:
        line = sys.stdin.readline()
        if not line:
            break

        line = line.strip()

        if line == "PING":
            print("PONG")
        elif line == "get":
            oid = sys.stdin.readline().strip()
            handle_get(oid)
        elif line == "getnext":
            oid = sys.stdin.readline().strip()
            handle_getnext(oid)

        sys.stdout.flush()


if __name__ == "__main__":
    main()