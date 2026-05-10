#!/usr/bin/env python3
"""
Controlador de tráfico para simulación de entrenamiento distribuido.

Simula el patrón de tráfico de un cluster de entrenamiento IA:
  1. Fase compute (forward + backward pass): sin tráfico de red
  2. Fase communicate (ring all-reduce): ráfagas RDMA al vecino del anillo

Ring all-reduce con 3 workers:
  W1 → W2 → W3 → W1

Uso:
  python3 traffic_controller.py --worker-id 1
  python3 traffic_controller.py --worker-id 2
  python3 traffic_controller.py --worker-id 3
"""

import argparse
import logging
import random
import signal
import subprocess
import time
import threading

# --- Configuración del anillo ---

RING = {
    1: {"ip": "10.10.0.1", "listen_port": 18501, "send_to": ("10.10.0.2", 18502)},
    2: {"ip": "10.10.0.2", "listen_port": 18502, "send_to": ("10.10.0.3", 18503)},
    3: {"ip": "10.10.0.3", "listen_port": 18503, "send_to": ("10.10.0.1", 18501)},
}

# --- Parámetros de tráfico ---

RXE_DEVICE = "rxe0"
GID_INDEX = 1

COMPUTE_TIME_BASE = 3.0        
COMPUTE_TIME_VARIANCE = 2.0    

MSG_SIZE = 65536               
DURATION = 2                   
TX_DEPTH = 32                  

INTER_ITERATION_BASE = 0.1
INTER_ITERATION_VARIANCE = 0.2

# --- Logging ---

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [W%(worker_id)s] %(message)s",
    datefmt="%H:%M:%S",
)

class TrafficController:
    """Controla la simulación de tráfico de un worker."""

    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self.config = RING[worker_id]
        self.running = True
        self.server_process = None
        self.server_thread = None
        self.iteration = 0

        self.logger = logging.getLogger(f"worker{worker_id}")
        self._log_extra = {"worker_id": worker_id}

    def log(self, msg: str, *args):
        self.logger.info(msg, *args, extra=self._log_extra)

    def log_warn(self, msg: str, *args):
        self.logger.warning(msg, *args, extra=self._log_extra)

    def _run_server_loop(self):
        port = self.config["listen_port"]
        self.log("Servidor escuchando en puerto %d", port)

        while self.running:
            cmd = [
                "ib_write_bw", "-d", RXE_DEVICE, "-x", str(GID_INDEX),
                "-p", str(port), "-s", str(MSG_SIZE), "-D", str(DURATION),
            ]
            try:
                self.server_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.server_process.wait()
            except Exception as e:
                if self.running:
                    self.log_warn("Error en servidor: %s", e)
                    time.sleep(1)

            if self.running:
                time.sleep(0.2)

        self.log("Servidor detenido")

    def start_server(self):
        self.server_thread = threading.Thread(target=self._run_server_loop, daemon=True)
        self.server_thread.start()

    def _send_to_neighbor(self) -> bool:
        target_ip, target_port = self.config["send_to"]
        cmd = [
            "ib_write_bw", "-d", RXE_DEVICE, "-x", str(GID_INDEX),
            "-p", str(target_port), "-s", str(MSG_SIZE), "-D", str(DURATION),
            target_ip,
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=DURATION + 10)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            self.log_warn("Timeout enviando a %s:%d", target_ip, target_port)
            return False
        except Exception as e:
            self.log_warn("Error enviando a %s:%d — %s", target_ip, target_port, e)
            return False

    def _compute_phase(self):
        duration = max(1.0, COMPUTE_TIME_BASE + random.uniform(-COMPUTE_TIME_VARIANCE, COMPUTE_TIME_VARIANCE))
        self.log("Iteración %d — compute (%.1fs)", self.iteration, duration)
        time.sleep(duration)

    def _communicate_phase(self):
        target_ip, target_port = self.config["send_to"]
        self.log("Iteración %d — all-reduce → %s:%d", self.iteration, target_ip, target_port)

        if not self._send_to_neighbor():
            self.log_warn("Reduce-scatter falló, reintentando en 2s...")
            time.sleep(2)
            self._send_to_neighbor()

        time.sleep(random.uniform(0.1, 0.3))

        if not self._send_to_neighbor():
            self.log_warn("All-gather falló, continuando...")

    def run(self):
        self.log("=== Controlador iniciado ===")
        self.start_server()
        time.sleep(2)
        
        startup_jitter = random.uniform(0, 1.0)
        self.log("Esperando %.1fs antes de comenzar...", startup_jitter)
        time.sleep(startup_jitter)

        while self.running:
            self.iteration += 1
            try:
                self._compute_phase()
                if not self.running: break
                
                self._communicate_phase()
                if not self.running: break

                pause = INTER_ITERATION_BASE + random.uniform(0, INTER_ITERATION_VARIANCE)
                time.sleep(pause)
            except Exception as e:
                self.log_warn("Error en iteración %d: %s", self.iteration, e)
                time.sleep(2)

        self.log("=== Controlador detenido tras %d iteraciones ===", self.iteration)

    def stop(self):
        self.running = False
        if self.server_process and self.server_process.poll() is None:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.server_process.kill()

def main():
    parser = argparse.ArgumentParser(description="Controlador de tráfico IA")
    parser.add_argument("--worker-id", type=int, choices=[1, 2, 3], required=True)
    args = parser.parse_args()

    controller = TrafficController(args.worker_id)

    def shutdown(sig, frame):
        controller.log("Recibida señal de parada")
        controller.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    controller.run()

if __name__ == "__main__":
    main()