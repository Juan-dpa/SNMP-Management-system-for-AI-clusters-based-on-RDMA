# 6 — TELEGRAM: ALERTAS

## Prerrequisitos

- `5-SIEM.md` completado correctamente.
- vm1, vm2, vm3 y switch en marcha (`start-traffic.sh`, `Config_OVS.sh`, `Network_Topology.sh`).

---

## Paso 1 — Copiar los archivos del proyecto

Clona el repositorio o copia manualmente estos tres archivos:

- `config.py`
- `telegram_alert.py`
- `syslog_alert_manager.py`

---

## Paso 2 — Habilitar SSH sin contraseña

Ejecuta esto en WSL y acepta todo con Enter:

```bash
ssh-keygen -t rsa -N ""
ssh-copy-id user@10.10.0.10
```

Verifica que `ssh user@10.10.0.10` conecta directamente sin pedir contraseña.

---

## Paso 3 — Eliminar reglas de prioridad 100

Ejecuta esto en el **switch**:

```bash
sudo ovs-ofctl del-flows br0 "ip,nw_dst=10.10.0.1"
sudo ovs-ofctl del-flows br0 "ip,nw_dst=10.10.0.2"
sudo ovs-ofctl del-flows br0 "ip,nw_dst=10.10.0.3"
exit
```

---

## Paso 4 — Configurar Snort

Conéctate por SSH al switch (`10.10.0.10`).

### 4.1 — `snort.conf`

```bash
sudo nano /etc/snort/snort.conf
```

Añade al final del archivo:

```
config checksum_mode: none
```

### 4.2 — `local.rules`

```bash
sudo nano /etc/snort/rules/local.rules
```

Añade al final:

```
alert tcp any any <> any any (msg:"MALWARE-C2 Comando de reconocimiento OS"; content:"/etc/os-release"; classtype:attempted-admin; sid:9900003; rev:2;)
alert tcp any any <> any any (msg:"MALWARE-C2 Exfiltracion de datos id"; content:"uid="; content:"gid="; content:"groups="; classtype:successful-admin; sid:9900004; rev:2;)
```

### 4.3 — Reiniciar Snort

```bash
sudo systemctl restart snort
sudo systemctl status snort
```

---

## Verificación

- `main.py` arranca sin errores.
- Las alertas de Kali llegan a Telegram (`wsl -d kali-linux` en PowerShell).
- Los botones **Ignorar**, **Limitar** y **Bloquear** funcionan visualmente en Grafana.

---

## Vuelta a la normalidad

Conéctate al switch:

```bash
ssh user@10.10.0.10
```

Elimina bloqueos:

```bash
sudo ovs-ofctl del-flows br0 "ip,nw_dst=10.10.0.1"
sudo ovs-ofctl del-flows br0 "ip,nw_dst=10.10.0.2"
sudo ovs-ofctl del-flows br0 "ip,nw_dst=10.10.0.3"
```

Elimina límites de tráfico:

```bash
sudo ovs-vsctl set interface enp0s2 ingress_policing_rate=0 ingress_policing_burst=0
sudo ovs-vsctl set interface enp0s3 ingress_policing_rate=0 ingress_policing_burst=0
sudo ovs-vsctl set interface enp0s4 ingress_policing_rate=0 ingress_policing_burst=0
```
