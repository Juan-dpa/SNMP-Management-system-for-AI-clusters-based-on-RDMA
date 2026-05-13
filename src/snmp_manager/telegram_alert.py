"""
Integración Telegram para alertas SOAR.

Envía alertas con botones interactivos y usa Long Polling para
escuchar la decisión del operador y ejecutar mitigaciones en el Switch.
"""

import asyncio
import json
import logging
import urllib.request
import urllib.parse
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from models import SnortAlert

logger = logging.getLogger(__name__)

# Mapeo de IPs a las interfaces de OVS basándonos en tu salida
INTERFACE_MAP = {
    "10.10.0.1": "enp0s2",  # vm1
    "10.10.0.2": "enp0s3",  # vm2
    "10.10.0.3": "enp0s4",  # vm3
}

class TelegramAlert:
    """Envía notificaciones y escucha comandos de mitigación vía Telegram."""

    def __init__(self):
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.last_update_id = 0

    def _request_sync(self, endpoint: str, data: dict = None) -> dict:
        """Hace la petición HTTP síncrona a Telegram."""
        url = f"{self.base_url}/{endpoint}"
        req_data = None
        
        if data:
            req_data = json.dumps(data).encode("utf-8")
            
        req = urllib.request.Request(url, data=req_data)
        if data:
            req.add_header("Content-Type", "application/json")
            
        try:
            with urllib.request.urlopen(req, timeout=35) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            logger.error(f"Error en API Telegram ({endpoint}): {e}")
            return {}

    async def send_alert(self, alert: SnortAlert) -> None:
        """Envía alerta con teclado de botones integrados."""
        if not self.bot_token or self.bot_token == "TU_TOKEN_AQUI":
            return

        mensaje = (
            f"🚨 <b>¡ALERTA DE SEGURIDAD DETECTADA!</b> 🚨\n\n"
            f"<b>Ataque:</b> {alert.attack_type}\n"
            f"<b>Origen:</b> {alert.source_ip}\n"
            f"<b>Víctima:</b> {alert.victim_ip} ({alert.victim_worker})\n"
            f"<b>Firma:</b> <code>{alert.signature_id}</code>\n"
            f"¿Qué acción deseas tomar?"
        )

        keyboard = {
            "inline_keyboard": [[
                {"text": "🔴 Bloquear", "callback_data": f"block_{alert.victim_ip}"},
                {"text": "🟡 Limitar", "callback_data": f"limit_{alert.victim_ip}"},
                {"text": "🟢 Ignorar", "callback_data": "ignore"}
            ]]
        }

        payload = {
            "chat_id": self.chat_id,
            "text": mensaje,
            "parse_mode": "HTML",
            "reply_markup": keyboard
        }
        
        await asyncio.to_thread(self._request_sync, "sendMessage", payload)

    async def send_trap_alert(self, worker_id: str, ip: str, pkts: str) -> None:
        """Envía una alerta a Telegram cuando se recibe un Trap de congestión."""
        if not self.bot_token or self.bot_token == "TU_TOKEN_AQUI":
            return

        mensaje = (
            f"🚨 <b>¡ALERTA DE CONGESTIÓN OVS!</b> 🚨\n\n"
            f"<b>Máquina:</b> {worker_id} ({ip})\n"
            f"<b>Detalle:</b> Alta congestión ECN detectada en la red.\n"
            f"<b>Impacto:</b> {pkts} paquetes marcados (InCEPkts).\n\n"
            f"<i>Estado: Monitoreando posible cuello de botella.</i>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": mensaje,
            "parse_mode": "HTML"
        }
        
        # Enviamos la petición sin bloquear el programa principal
        await asyncio.to_thread(self._request_sync, "sendMessage", payload)


    async def execute_mitigation(self, action: str, ip: str) -> str:
        """Ejecuta comandos SSH contra el Switch OVS."""
        if action == "ignore":
            return "Alerta ignorada. No se aplicaron cambios."

        interface = INTERFACE_MAP.get(ip)
        if not interface:
            return f"Error: No se encontró la interfaz física para la IP {ip}."

        if action == "block":
            # Usamos OpenFlow para descartar paquetes hacia esa IP
            cmd = f'ssh user@10.10.0.10 sudo ovs-ofctl add-flow br0 "priority=200,ip,nw_dst={ip},actions=drop"'
            msg = f"Tráfico hacia {ip} BLOQUEADO en OVS."
        elif action == "limit":
            # Usamos QoS/Policing para ahogar la conexión (1Mbps aprox)
            cmd = f'ssh user@10.10.0.10 sudo ovs-vsctl set interface {interface} ingress_policing_rate=1000 ingress_policing_burst=100'
            msg = f"Tráfico de {ip} ({interface}) LIMITADO por QoS."
        else:
            return "Acción desconocida."

        logger.info(f"Ejecutando mitigación: {cmd}")
        process = await asyncio.create_subprocess_shell(cmd)
        await process.communicate()
        
        if process.returncode == 0:
            return f"✅ Éxito: {msg}"
        else:
            return f"❌ Fallo al ejecutar comando SSH (Código {process.returncode})."

    async def start_polling(self) -> None:
        """Bucle infinito de Long Polling para escuchar los botones."""
        if not self.bot_token or self.bot_token == "TU_TOKEN_AQUI":
            logger.warning("Telegram deshabilitado. No se iniciará el Polling.")
            return

        logger.info("Iniciando escucha de comandos de Telegram (Long Polling)...")
        while True:
            # timeout=30 mantiene la conexión abierta ahorrando recursos
            payload = {"offset": self.last_update_id + 1, "timeout": 30}
            response = await asyncio.to_thread(self._request_sync, "getUpdates", payload)
            
            if response and response.get("ok"):
                for update in response.get("result", []):
                    self.last_update_id = update["update_id"]
                    
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        cb_id = cb["id"]
                        data = cb["data"]  # ej: "block_10.10.0.3"
                        message_id = cb["message"]["message_id"]

                        # 1. Quitar el "Reloj" de carga del botón
                        await asyncio.to_thread(self._request_sync, "answerCallbackQuery", {"callback_query_id": cb_id})
                        
                        # 2. Procesar acción
                        action, *ip_parts = data.split("_")
                        ip = ip_parts[0] if ip_parts else ""
                        
                        result_msg = await self.execute_mitigation(action, ip)
                        logger.info(f"Telegram mitigación: {result_msg}")

                        # 3. Editar el mensaje para quitar los botones e informar del resultado
                        new_text = cb["message"]["text"] + f"\n\n<b>Resolución:</b> {result_msg}"
                        edit_payload = {
                            "chat_id": self.chat_id,
                            "message_id": message_id,
                            "text": new_text,
                            "parse_mode": "HTML"
                        }
                        await asyncio.to_thread(self._request_sync, "editMessageText", edit_payload)

            await asyncio.sleep(1)
