Aquí tienes un documento de contexto **"System Prompt / Context Briefing"** redactado específicamente de "IA a IA". Está diseñado con la densidad técnica, estructura y directrices explícitas que un agente de programación (como un LLM) necesita para entender el estado del sistema, la topología, y lo que no debe hacer basándose en nuestras sesiones de *troubleshooting*.

Puedes copiar todo el bloque a continuación y pasárselo a tu agente IA:

---

# 📋 CONTEXT BRIEFING PARA AGENTE IA: Implementación de Módulo SOAR (Syslog + OVS)

## 1. Contexto Global del Proyecto

El sistema es una plataforma de monitorización y gestión automatizada para un clúster RoCEv2 simulado sobre QEMU/KVM en WSL2. El gestor (escrito en Python) recolecta métricas de rendimiento vía SNMP de manera asíncrona y las almacena en InfluxDB.

El objetivo actual es expandir este gestor hacia una plataforma **SOAR (Security Orchestration, Automation, and Response)**. Para ello, se ha integrado un IDS (Snort 3) que monitoriza la red. El gestor debe escuchar las alertas de Snort en tiempo real, procesarlas asíncronamente y ejecutar acciones de mitigación.

## 2. Topología de Red y Actores

* **Host WSL (Gestor Python):** IP `10.10.0.254`. Centraliza la lógica. Escucha SNMP Traps (UDP 1162) y ahora debe escuchar Syslog (UDP 1514).
* **Switch OVS (QEMU VM):** IP `10.10.0.10`. Contiene Open vSwitch y el IDS (Snort).
* **Workers 1, 2 y 3 (QEMU VMs):** IPs `10.10.0.1`, `10.10.0.2` y `10.10.0.3`. El Worker 3 es el objetivo principal de ataques simulados (ej. C2 Beaconing, Escaneos Nmap).
* **Port Mirroring:** En el Switch, OVS copia todo el tráfico de los 3 workers hacia una interfaz interna llamada `mirror0`.

## 3. Arquitectura de Seguridad y Flujo de Alertas (Push Model)

Hemos descartado explícitamente el uso de *SSH Tailing* por ser una mala práctica en producción. El flujo de alertas funciona exclusivamente mediante **Log Forwarding (Syslog)**:

1. **Snort (IDS)** escucha en `mirror0`. Cuando detecta un ataque (ej. escaneo SYN), genera una alerta y la envía al socket syslog local etiquetada como `LOG_AUTH`.
2. **Rsyslog** en el Switch intercepta los mensajes de Snort gracias a una regla (`:programname, startswith, "snort"`).
3. **Forwarding UDP:** Rsyslog empaqueta estas alertas en datagramas UDP crudos y los envía a la IP del Gestor (`10.10.0.254`) por el puerto no privilegiado **1514**.

## 4. Arquitectura del Gestor Python (`snmp_manager`)

* **Stack:** Python 3.12+, `asyncio` nativo, sin dependencias bloqueantes.
* **Diseño:** Bucle de eventos principal (`loop.run_until_complete()`). Actualmente conviven un poller de SNMP (cada 5s) y un `trap_receiver.py` (UDP 1162 usando `asyncio.DatagramProtocol`).
* **Filosofía:** No bloquear NUNCA el *event loop*. Cualquier entrada/salida (I/O) debe ser no bloqueante.

## 5. Misión del Agente (Tareas a Implementar)

Se requiere que desarrolles el código para ingerir estas alertas e integrarlo en el `main.py`.

**Tarea 1: Crear `syslog_receiver.py**`

* Implementar un servidor UDP usando `asyncio.DatagramProtocol` que escuche en `0.0.0.0:1514`.
* Parsear los datagramas recibidos (texto plano en formato Syslog, ej: `<81>May 10 21:00:00 switch snort[1234]: [1:1228:7] SCAN nmap XMAS... {TCP} 10.10.0.254:44526 -> 10.10.0.3:161`).
* Extraer mediante expresiones regulares la IP de la víctima (destino del ataque) y el tipo de ataque.
* Ejecutar un *callback* inyectado desde el orquestador principal.

**Tarea 2: Integración en `main.py` y Lógica de Mitigación (SOAR)**

* Instanciar el receptor de Syslog y acoplarlo al *event loop* existente.
* Crear la función *callback* que procese la alerta.

## 6. Antipatrones y Lecciones Aprendidas (¡CRÍTICO!)

Para asegurar el éxito de la implementación, debes evitar los siguientes errores que hemos identificado en el diseño:

1. **Alert Fatigue / Spam (Ataques Ruidosos):** Snort generará CIENTOS de mensajes UDP por segundo durante un ataque Nmap. **Debes implementar un sistema de Throttling/Debouncing (ej. un diccionario de *cooldown* en memoria).** Si no mitigas esto, el *callback* se ejecutará cientos de veces por segundo, colapsando futuros bots de Telegram o llamadas a la API de OVS. Registra y mitiga una IP, y luego ignora alertas para esa IP durante X minutos.
2. **Mapeo IP a Puerto OVS:** Snort reporta IPs (`10.10.0.3`), pero para la futura mitigación en el Switch (ej. apagar un puerto), OVS requiere nombres de interfaz (`enp0s4`). El gestor debe tener un mapeo u objeto de configuración para traducir la IP de la víctima a la interfaz OVS correspondiente antes de plantear la acción de mitigación.
3. **Cero Bloqueos:** El procesamiento de *regex* en el `datagram_received` debe ser rápido. Si se planea invocar llamadas externas en el *callback*, asegúrate de envolverlas en tareas asíncronas (`asyncio.create_task()`).
4. **No usar SNMP para logs:** Bajo ninguna circunstancia intentes convertir las alertas de Snort en Traps SNMP. El pipeline debe ser puramente UDP crudo -> Python.

*** ### (Opcional para el humano)
*Cuando le pases esto al agente, te sugiero que le añadas al final tu petición concreta, algo como: "Basándote en este contexto, genérame el código completo para `syslog_receiver.py` y muéstrame exactamente cómo modificar `main.py` para inyectar el callback con el sistema anti-spam incluido."*
