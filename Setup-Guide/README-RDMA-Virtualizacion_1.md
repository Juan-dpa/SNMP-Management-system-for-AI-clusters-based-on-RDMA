# Guía de despliegue: Topología RDMA con Soft-RoCE sobre QEMU/KVM en WSL2

## Índice

1. Contexto y justificación de la arquitectura
2. Requisitos previos
3. Instalación y verificación de QEMU con KVM
4. Preparación de la imagen base con Soft-RoCE
5. Configuración de la red del host (bridge + TAP)
6. Arranque y configuración de las VMs
7. Configuración de Soft-RoCE dentro de las VMs
8. Prueba de tráfico RDMA entre VMs
9. Captura y análisis con Wireshark
10. Contadores disponibles para monitorización
11. Scripts de automatización
12. Problemas frecuentes y soluciones

---

## 1. Contexto y justificación de la arquitectura

### Por qué VMs y no contenedores

Durante el desarrollo del proyecto se exploraron tres aproximaciones para simular múltiples nodos RDMA dentro de WSL2:

**Network namespaces (`ip netns`):** fallaron porque el driver `rdma_rxe` crea un único socket UDP en el puerto 4791 en el network namespace raíz del kernel. Al crear dispositivos `rxe` dentro de namespaces separados, el tráfico RDMA no podía alcanzar las IPs de otros namespaces, muriendo silenciosamente sin generar ningún paquete UDP.

**Contenedores Docker:** sufren el mismo problema. Comparten kernel con el host, y el socket UDP:4791 del driver sigue viviendo en el namespace raíz, no en el namespace de cada contenedor.

**Máquinas virtuales QEMU:** cada VM tiene su propio kernel, su propia instancia del driver `rdma_rxe` y su propio socket UDP:4791 independiente. El tráfico RoCEv2 sale como paquetes UDP reales por la interfaz virtual de cada VM, cruza el bridge del host y llega a la otra VM. Esta es la única aproximación que genera tráfico RDMA real capturable en la red.

## 2. Requisitos previos

### Sistema operativo

- **Windows 11** (obligatorio para virtualización anidada en WSL2).
- WSL2 instalado y actualizado. Verificar versión desde PowerShell:

```powershell
wsl --version
```

Si la versión es anterior a 2.0.0:

```powershell
wsl --update
```

### Hardware

- CPU con soporte de virtualización (Intel VT-x o AMD-V) habilitado en BIOS.
- Mínimo 16 GB de RAM recomendado (WSL + 2 VMs de 2 GB cada una).
- 15 GB de disco libre para imágenes de VM.

### Configuración de WSL

Editar (o crear) el archivo `C:\Users\<USUARIO_WINDOWS>\.wslconfig`:

```ini
[wsl2]
nestedVirtualization=true
memory=8GB
processors=4
```

Reiniciar WSL desde PowerShell:

```powershell
wsl --shutdown
```

Abrir WSL y verificar acceso a KVM:

```bash
ls -la /dev/kvm
```

Debe mostrar el dispositivo `/dev/kvm`. Si no aparece, verificar que `nestedVirtualization=true` está en `.wslconfig` y que WSL se reinició correctamente.

### Identificar el usuario de Windows

Varios pasos de esta guía requieren copiar archivos entre WSL y Windows. Para saber el nombre exacto del usuario:

```bash
cmd.exe /c 'echo %USERNAME%'
```

En esta guía se usa `<USUARIO_WINDOWS>` como placeholder. Sustituir siempre por el valor real.

---

## 3. Instalación y verificación de QEMU con KVM

```bash
sudo apt update
sudo apt install -y qemu-system-x86 qemu-utils cloud-image-utils \
    bridge-utils iproute2 wget genisoimage
```

Verificar que QEMU detecta KVM:

```bash
qemu-system-x86_64 -accel help
```

Debe listar `kvm` entre los aceleradores disponibles. Si solo aparece `tcg`, KVM no está funcional; las VMs funcionarán igualmente pero con rendimiento reducido.

---

## 4. Preparación de la imagen base con Soft-RoCE

Se prepara una única imagen con todos los paquetes necesarios preinstalados. Las VMs finales se crean como copias ligeras de esta base, evitando repetir la instalación de paquetes en cada VM.

### 4.1 Descargar imagen cloud de Ubuntu

```bash
mkdir -p ~/qemu-roce && cd ~/qemu-roce
wget https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img
```

### 4.2 Crear disco de preparación

```bash
qemu-img create -f qcow2 -b jammy-server-cloudimg-amd64.img -F qcow2 prep.qcow2 10G
```

### 4.3 Crear cloud-init para la preparación

Cloud-init configura usuario y contraseña al primer arranque.

```bash
mkdir -p ~/qemu-roce/cloud-init/prep
```

Crear `~/qemu-roce/cloud-init/prep/user-data`:

```yaml
#cloud-config
hostname: prep
manage_etc_hosts: true
users:
  - name: user
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: "rdma"
ssh_pwauth: true
```

Crear `~/qemu-roce/cloud-init/prep/meta-data`:

```yaml
instance-id: prep
local-hostname: prep
```

Generar el ISO:

```bash
genisoimage -output ~/qemu-roce/seed-prep.iso -volid cidata -joliet -rock \
    ~/qemu-roce/cloud-init/prep/user-data \
    ~/qemu-roce/cloud-init/prep/meta-data
```

### 4.4 Arrancar con red de usuario (NAT automático)

```bash
sudo qemu-system-x86_64 \
    -name prep \
    -machine q35,accel=kvm \
    -cpu host \
    -m 2048 \
    -smp 2 \
    -drive file=$HOME/qemu-roce/prep.qcow2,format=qcow2,if=virtio \
    -drive file=$HOME/qemu-roce/seed-prep.iso,format=raw,if=virtio \
    -netdev user,id=net0 \
    -device virtio-net-pci,netdev=net0 \
    -nographic \
    -serial mon:stdio
```

La clave es `-netdev user`: QEMU proporciona DHCP y NAT automáticamente sin configurar nada en el host. Esperar al login (usuario: `user`, contraseña: `rdma`).

### 4.5 Instalar paquetes dentro de la VM

```bash
sudo apt update
sudo apt install -y \
    linux-modules-extra-$(uname -r) \
    rdma-core \
    ibverbs-utils \
    perftest \
    iproute2 \
    ethtool \
    tcpdump \
    snmpd \
    snmp \
    snmp-mibs-downloader
```

Verificar que el módulo RDMA carga correctamente:

```bash
sudo modprobe rdma_rxe
lsmod | grep rdma_rxe
```

Si `modprobe` falla, el paquete `linux-modules-extra` no se instaló correctamente. Verificar con `dpkg -l | grep linux-modules-extra`.

Limpiar caché para reducir tamaño de la imagen:

```bash
sudo apt clean
```

### 4.6 Apagar y consolidar

```bash
sudo poweroff
```

De vuelta en el host WSL, consolidar la imagen en un fichero independiente:

```bash
cd ~/qemu-roce
qemu-img convert -O qcow2 prep.qcow2 base-roce.qcow2
```

`base-roce.qcow2` es la imagen base con todo preinstalado. Este fichero es un artefacto compartible: cualquier compañero puede copiarlo y crear VMs derivadas sin repetir la instalación.

### 4.7 Crear discos para las VMs finales

```bash
qemu-img create -f qcow2 -b base-roce.qcow2 -F qcow2 vm1.qcow2 10G
qemu-img create -f qcow2 -b base-roce.qcow2 -F qcow2 vm2.qcow2 10G
```

Cada disco ocupa solo el delta respecto a la base (unos pocos MB inicialmente).

### 4.8 Crear cloud-init para cada VM

#### VM1

```bash
mkdir -p ~/qemu-roce/cloud-init/vm1
```

`~/qemu-roce/cloud-init/vm1/user-data`:

```yaml
#cloud-config
hostname: vm1
manage_etc_hosts: true
users:
  - name: user
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: "rdma"
ssh_pwauth: true
```

`~/qemu-roce/cloud-init/vm1/meta-data`:

```yaml
instance-id: vm1
local-hostname: vm1
```

```bash
genisoimage -output ~/qemu-roce/seed-vm1.iso -volid cidata -joliet -rock \
    ~/qemu-roce/cloud-init/vm1/user-data \
    ~/qemu-roce/cloud-init/vm1/meta-data
```

#### VM2

```bash
mkdir -p ~/qemu-roce/cloud-init/vm2
```

`~/qemu-roce/cloud-init/vm2/user-data`:

```yaml
#cloud-config
hostname: vm2
manage_etc_hosts: true
users:
  - name: user
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: "rdma"
ssh_pwauth: true
```

`~/qemu-roce/cloud-init/vm2/meta-data`:

```yaml
instance-id: vm2
local-hostname: vm2
```

```bash
genisoimage -output ~/qemu-roce/seed-vm2.iso -volid cidata -joliet -rock \
    ~/qemu-roce/cloud-init/vm2/user-data \
    ~/qemu-roce/cloud-init/vm2/meta-data
```

---

## 5. Configuración de la red del host (bridge + TAP)

### 5.1 Crear la topología

```bash
# Bridge (switch virtual L2)
sudo ip link add br-roce type bridge
sudo ip link set br-roce up

# TAP para VM1
sudo ip tuntap add dev tap0 mode tap
sudo ip link set tap0 master br-roce
sudo ip link set tap0 up

# TAP para VM2
sudo ip tuntap add dev tap1 mode tap
sudo ip link set tap1 master br-roce
sudo ip link set tap1 up

# IP en el bridge para acceso SSH desde el host
sudo ip addr add 10.10.0.254/24 dev br-roce
```

### 5.2 Configurar iptables

Docker (si está instalado) configura iptables con política FORWARD DROP, lo que bloquea el tráfico del bridge. Aplicar estas reglas:

```bash
# Evitar que iptables filtre tráfico del bridge
sudo sysctl -w net.bridge.bridge-nf-call-iptables=0
sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0

# Permitir explícitamente el tráfico del bridge
sudo iptables -I FORWARD -i br-roce -o br-roce -j ACCEPT

# Habilitar forwarding
sudo sysctl -w net.ipv4.ip_forward=1
```

### 5.3 Verificar

```bash
bridge link show
```

Debe listar `tap0` y `tap1` asociados a `br-roce`, ambos en estado `forwarding`.

### 5.4 Persistencia

Esta configuración de red no sobrevive a un reinicio de WSL. Usar el script `start-topology.sh` de la sección 11 para recrearla rápidamente.

---

## 6. Arranque y configuración de las VMs

### 6.1 Arrancar VM1

En una terminal WSL:

```bash
sudo qemu-system-x86_64 \
    -name vm1 \
    -machine q35,accel=kvm \
    -cpu host \
    -m 2048 \
    -smp 2 \
    -drive file=$HOME/qemu-roce/vm1.qcow2,format=qcow2,if=virtio \
    -drive file=$HOME/qemu-roce/seed-vm1.iso,format=raw,if=virtio \
    -netdev tap,id=net0,ifname=tap0,script=no,downscript=no \
    -device virtio-net-pci,netdev=net0,mac=52:54:00:00:00:01 \
    -nographic \
    -serial mon:stdio
```

### 6.2 Arrancar VM2

En otra terminal WSL:

```bash
sudo qemu-system-x86_64 \
    -name vm2 \
    -machine q35,accel=kvm \
    -cpu host \
    -m 2048 \
    -smp 2 \
    -drive file=$HOME/qemu-roce/vm2.qcow2,format=qcow2,if=virtio \
    -drive file=$HOME/qemu-roce/seed-vm2.iso,format=raw,if=virtio \
    -netdev tap,id=net0,ifname=tap1,script=no,downscript=no \
    -device virtio-net-pci,netdev=net0,mac=52:54:00:00:00:02 \
    -nographic \
    -serial mon:stdio
```

### 6.3 Parámetros relevantes

| Parámetro | Función |
|---|---|
| `-machine q35,accel=kvm` | Chipset Q35 con aceleración KVM |
| `-cpu host` | Expone la CPU real del host. Con `accel=tcg`, usar `-cpu max` |
| `-m 2048` | 2 GB de RAM por VM |
| `-smp 2` | 2 cores por VM |
| `-nographic -serial mon:stdio` | Consola de la VM directamente en la terminal |
| `script=no,downscript=no` | No ejecutar scripts automáticos al crear/destruir el TAP |

### 6.4 Login

Esperar a que aparezca el prompt de login (1-2 minutos en el primer arranque). Credenciales: `user` / `rdma`.

### 6.5 Configurar red dentro de cada VM

Verificar el nombre de la interfaz de red:

```bash
ip link show
```

La interfaz (que no sea `lo`) suele llamarse `enp0s2`, `ens2` o `eth0`.

En VM1:

```bash
sudo ip addr add 10.10.0.1/24 dev enp0s2
sudo ip link set enp0s2 up
```

En VM2:

```bash
sudo ip addr add 10.10.0.2/24 dev enp0s2
sudo ip link set enp0s2 up
```

Verificar conectividad desde VM1:

```bash
ping -c 2 10.10.0.2
```

### 6.6 Gestión de las VMs

Apagar desde dentro: `sudo poweroff`

Monitor QEMU: `Ctrl+A` seguido de `C`. Escribir `quit` para forzar apagado.

Acceso SSH desde el host WSL:

```bash
ssh user@10.10.0.1    # VM1
ssh user@10.10.0.2    # VM2
```

Contraseña: `rdma`.

---

## 7. Configuración de Soft-RoCE dentro de las VMs

Ejecutar en cada VM (sustituir `enp0s2` por el nombre real de la interfaz si difiere):

```bash
# Cargar el módulo
sudo modprobe rdma_rxe

# Crear el dispositivo RDMA asociado a la interfaz de red
sudo rdma link add rxe0 type rxe netdev enp0s2

# Desactivar offloads para evitar problemas de checksum
sudo ethtool -K enp0s2 tx off rx off tso off gso off gro off

# Verificar
rdma link
ibv_devices
ibv_devinfo -d rxe0
```

Verificar que el GID índice 1 contiene la IP IPv4-mapped:

```bash
cat /sys/class/infiniband/rxe0/ports/1/gids/1
```

El valor debe ser `0000:0000:0000:0000:0000:ffff:0a0a:0001` (para 10.10.0.1) o `...0a0a:0002` (para 10.10.0.2). El formato `0a0a:0001` se decodifica como `10.10.0.1`.

### GID: qué es y por qué importa

GID (Global Identifier) es el equivalente RDMA de una dirección IP. Cada dispositivo RDMA tiene una tabla de GIDs:

| Índice | Contenido | Uso |
|---|---|---|
| 0 | IPv6 link-local (derivado de la MAC) | No usar: intenta encapsular sobre IPv6 sin routing configurado |
| 1 | IPv4-mapped (derivado de la IP asignada) | Usar siempre con `-g 1` en las herramientas de test |

Usar `-g 0` causa que el driver encapsule sobre UDP/IPv6. Sin routing IPv6 entre las VMs, los paquetes mueren silenciosamente y el test falla con `Work Request Flushed Error` sin ningún mensaje de error claro.

---

## 8. Prueba de tráfico RDMA entre VMs

### 8.1 Test de conectividad RDMA (ping-pong)

En VM2 (servidor):

```bash
ibv_rc_pingpong -d rxe0 -g 1
```

En VM1 (cliente):

```bash
ibv_rc_pingpong -d rxe0 -g 1 10.10.0.2
```

Resultado esperado en ambos extremos:

```
local address:  LID 0x0000, QPN 0x000011, PSN 0x..., GID ::ffff:10.10.0.1
remote address: LID 0x0000, QPN 0x000012, PSN 0x..., GID ::ffff:10.10.0.2
8192000 bytes in 0.xx seconds = xxxx Mbit/sec
1000 iters in 0.xx seconds = xx.xx usec/iter
```

### 8.2 Tests de rendimiento adicionales

```bash
# Ancho de banda con SEND
# VM2: ib_send_bw -d rxe0
# VM1: ib_send_bw -d rxe0 10.10.0.2

# Ancho de banda con RDMA WRITE
# VM2: ib_write_bw -d rxe0
# VM1: ib_write_bw -d rxe0 10.10.0.2

# Latencia con RDMA WRITE
# VM2: ib_write_lat -d rxe0
# VM1: ib_write_lat -d rxe0 10.10.0.2
```

---

## 9. Captura y análisis con Wireshark

### 9.1 Capturar tráfico en el bridge

Desde el host WSL (tercera terminal):

```bash
sudo tcpdump -i br-roce -w /tmp/roce.pcap
```

Lanzar un test de pingpong entre las VMs. Cuando termine, Ctrl+C en tcpdump.

### 9.2 Copiar a Windows y abrir en Wireshark

```bash
cp /tmp/roce.pcap /mnt/c/Users/<USUARIO_WINDOWS>/Desktop/roce.pcap
```

Abrir `roce.pcap` con Wireshark en Windows. Wireshark reconoce automáticamente el tráfico RoCEv2 (UDP:4791) y activa el disector InfiniBand.

### 9.3 Filtros útiles

| Filtro | Qué muestra |
|---|---|
| `udp.port == 4791` | Todo el tráfico RoCEv2 |
| `infiniband` | Solo paquetes con cabeceras InfiniBand decodificadas |
| `infiniband.bth.opcode` | Filtrar por tipo de operación |
| `ip.addr == 10.10.0.1` | Tráfico desde/hacia VM1 |
| `tcp.port == 18515` | Canal de control del pingpong (setup de QPs) |

### 9.4 Qué se observa en la captura

Un flujo de pingpong típico muestra:

1. TCP al puerto 18515 al inicio: servidor y cliente intercambian parámetros de QP (GIDs, QPN, PSN).
2. UDP al puerto 4791: tráfico RDMA real con cabeceras InfiniBand decodificadas (BTH con SEND, ACK, etc.).
3. TCP de cierre al finalizar.

---

## 10. Contadores disponibles para monitorización

### 10.1 Contadores estándar del puerto

Ubicación: `/sys/class/infiniband/rxe0/ports/1/counters/`

```bash
for f in /sys/class/infiniband/rxe0/ports/1/counters/*; do
    echo "$(basename $f): $(cat $f)"
done
```

| Contador | Qué mide | Nota |
|---|---|---|
| `port_xmit_data` | Datos transmitidos | Unidades de 4 bytes. Multiplicar por 4 para obtener bytes |
| `port_rcv_data` | Datos recibidos | Misma unidad |
| `port_xmit_packets` | Paquetes transmitidos | |
| `port_rcv_packets` | Paquetes recibidos | |
| `port_xmit_discards` | Paquetes descartados al transmitir | |
| `port_rcv_errors` | Errores en recepción | |
| `unicast_xmit_packets` | Tráfico unicast TX | |
| `unicast_rcv_packets` | Tráfico unicast RX | |
| `multicast_xmit_packets` | Tráfico multicast TX | |
| `multicast_rcv_packets` | Tráfico multicast RX | |

### 10.2 Contadores específicos de Soft-RoCE

Ubicación: `/sys/class/infiniband/rxe0/ports/1/hw_counters/`

```bash
for f in /sys/class/infiniband/rxe0/ports/1/hw_counters/*; do
    echo "$(basename $f): $(cat $f)"
done
```

| Contador | Qué mide | Relevancia para monitorización |
|---|---|---|
| `sent_pkts` | Paquetes procesados por el driver (TX) | Tráfico total |
| `rcvd_pkts` | Paquetes procesados por el driver (RX) | Tráfico total |
| `send_err` | Errores en la ruta de envío | Indicador de problemas |
| `rcvd_seq_err` | Errores de secuencia en recepción | Indicador de congestión |
| `out_of_seq_request` | Requests fuera de secuencia | Indicador de congestión |
| `duplicate_request` | Requests duplicadas detectadas | Retransmisiones |
| `retry_exceeded_err` | Reintentos agotados (timeout) | Congestión severa |
| `retry_rnr_exceeded_err` | Reintentos RNR agotados | Receptor saturado |
| `rcvd_rnr_err` | Recepciones con Receiver Not Ready | Presión en el receptor |
| `send_rnr_err` | Envíos con Receiver Not Ready | Presión en el receptor |
| `ack_deferred` | ACKs diferidos | Carga del receptor |
| `rdma_sends` | Operaciones RDMA SEND | Tipo de tráfico |
| `rdma_recvs` | Operaciones RDMA RECV | Tipo de tráfico |
| `link_downed` | Veces que el link cayó | Estabilidad |
| `completer_retry_err` | Errores en el completer | Diagnóstico interno |

### 10.3 Contadores ECN (nivel IP)

Ubicación: `/proc/net/netstat`, línea `IpExt`.

```bash
awk '/IpExt:/ && !/^IpExt: [A-Z]/ {print "InCEPkts:", $18, "InECT0Pkts:", $17, "InECT1Pkts:", $16, "InNoECTPkts:", $15}' /proc/net/netstat
```

| Campo | Equivalente MIB | Qué mide |
|---|---|---|
| `InCEPkts` | `ipIfStatsInCEPkts` (IP-MIB) | Paquetes marcados con CE (Congestion Experienced) |
| `InECT0Pkts` | - | Paquetes con bit ECT(0) |
| `InECT1Pkts` | - | Paquetes con bit ECT(1) |
| `InNoECTPkts` | - | Paquetes sin bits ECT (tráfico normal) |

Estos contadores están a cero en condiciones normales porque no hay elementos de red marcando congestión. Se pueden simular con `tc netem ecn` en el bridge del host para probar el pipeline de monitorización.

### 10.4 Contadores PAUSE (802.3x)

Dependen del driver de la NIC virtual. Con `virtio-net` (configuración por defecto) no están disponibles. Para obtenerlos, cambiar el driver de red de QEMU a `igb` (emula Intel I350):

En el comando de arranque de QEMU, cambiar:

```
-device virtio-net-pci,netdev=net0,mac=...
```

Por:

```
-device igb,netdev=net0,mac=...
```

Dentro de la VM, verificar:

```bash
ethtool -S enp0s2 | grep -i pause
```

### 10.5 Contadores no disponibles en Soft-RoCE

| Métrica | Por qué no disponible | Alternativa |
|---|---|---|
| PFC por prioridad (802.1Qbb) | Requiere hardware DCB real | Documentar en la MIB como OID definido pero no poblable |
| CNP (Congestion Notification Packets) | Soft-RoCE no implementa DCQCN | Documentar en la MIB como OID definido pero no poblable |

### 10.6 Verificar movimiento de contadores

Hacer un antes/después del pingpong para confirmar que los contadores funcionan:

```bash
# Snapshot antes
for f in /sys/class/infiniband/rxe0/ports/1/hw_counters/*; do
    echo "$(basename $f): $(cat $f)"
done

# Lanzar test de tráfico desde la otra VM

# Snapshot después
for f in /sys/class/infiniband/rxe0/ports/1/hw_counters/*; do
    echo "$(basename $f): $(cat $f)"
done
```

### 10.7 Formato JSON para automatización

```bash
rdma statistic show link rxe0 -j -p
```

Esta salida es el formato natural para integración con Telegraf/InfluxDB.

---

## 11. Scripts de automatización

### start-topology.sh

Crea la infraestructura de red del host:

```bash
#!/bin/bash
set -e

echo "=== Creando bridge y TAPs ==="
sudo ip link add br-roce type bridge 2>/dev/null || true
sudo ip link set br-roce up

for i in 0 1; do
    sudo ip tuntap add dev tap$i mode tap 2>/dev/null || true
    sudo ip link set tap$i master br-roce
    sudo ip link set tap$i up
done

sudo ip addr add 10.10.0.254/24 dev br-roce 2>/dev/null || true

echo "=== Configurando iptables ==="
sudo sysctl -w net.bridge.bridge-nf-call-iptables=0 > /dev/null
sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=0 > /dev/null
sudo iptables -I FORWARD -i br-roce -o br-roce -j ACCEPT 2>/dev/null || true
sudo sysctl -w net.ipv4.ip_forward=1 > /dev/null

echo "=== Topología lista ==="
bridge link show
echo ""
echo "Lanzar las VMs:"
echo "  ./start-vm.sh 1"
echo "  ./start-vm.sh 2"
```

### start-vm.sh

Arranca una VM por ID:

```bash
#!/bin/bash
VM_ID=${1:?Uso: ./start-vm.sh <1|2>}
TAP_ID=$((VM_ID - 1))
MAC="52:54:00:00:00:0${VM_ID}"
DIR="$HOME/qemu-roce"

sudo qemu-system-x86_64 \
    -name "vm${VM_ID}" \
    -machine q35,accel=kvm \
    -cpu host \
    -m 2048 \
    -smp 2 \
    -drive "file=${DIR}/vm${VM_ID}.qcow2,format=qcow2,if=virtio" \
    -drive "file=${DIR}/seed-vm${VM_ID}.iso,format=raw,if=virtio" \
    -netdev "tap,id=net0,ifname=tap${TAP_ID},script=no,downscript=no" \
    -device "virtio-net-pci,netdev=net0,mac=${MAC}" \
    -nographic \
    -serial mon:stdio
```

### setup-roce.sh

Configura Soft-RoCE dentro de una VM (ejecutar desde la VM):

```bash
#!/bin/bash
set -e

# Detectar la interfaz de red (primera que no sea lo)
IFACE=$(ip -o link show | awk -F': ' '!/lo/{print $2; exit}')
echo "Interfaz detectada: $IFACE"

sudo modprobe rdma_rxe
sudo rdma link add rxe0 type rxe netdev "$IFACE"
sudo ethtool -K "$IFACE" tx off rx off tso off gso off gro off 2>/dev/null || true

echo "=== Estado RDMA ==="
rdma link
ibv_devices
echo ""
echo "GID IPv4-mapped:"
cat /sys/class/infiniband/rxe0/ports/1/gids/1
```

### cleanup.sh

Limpia la topología de red del host:

```bash
#!/bin/bash
echo "=== Limpiando topología ==="
for i in 0 1; do
    sudo ip link del tap$i 2>/dev/null || true
done
sudo ip link del br-roce 2>/dev/null || true
echo "Topología eliminada."
```

Hacer ejecutables:

```bash
chmod +x start-topology.sh start-vm.sh setup-roce.sh cleanup.sh
```

---

## 12. Problemas frecuentes y soluciones

### "Could not access KVM kernel module: No such file or directory"

`/dev/kvm` no existe. Verificar `nestedVirtualization=true` en `.wslconfig`, que el host es Windows 11, y reiniciar WSL con `wsl --shutdown`.

Alternativa sin KVM (rendimiento reducido): cambiar `-machine q35,accel=kvm` por `-machine q35,accel=tcg` y `-cpu host` por `-cpu max`.

### Las VMs no se ven entre sí (ping falla)

1. Verificar que los TAPs están en el bridge: `bridge link show`.
2. Verificar iptables: `sudo iptables -L FORWARD -v -n`. Si la política es DROP y no hay regla para `br-roce`, aplicar las reglas de la sección 5.2.
3. Verificar que las IPs están asignadas dentro de las VMs: `ip addr show`.

### `modprobe rdma_rxe` falla dentro de la VM

El kernel de la VM no tiene el módulo. Si la imagen base se preparó correctamente (sección 4), esto no debería ocurrir. Si ocurre, instalar dentro de la VM:

```bash
sudo apt install -y linux-modules-extra-$(uname -r)
sudo modprobe rdma_rxe
```

Para instalar paquetes, la VM necesita internet. Arrancarla temporalmente con `-netdev user` en vez de `-netdev tap` (ver sección 4.4).

### `ibv_rc_pingpong` da "Failed status Work Request Flushed Error"

Verificar que se usa `-g 1` y no `-g 0`. Con `-g 0` el driver intenta usar IPv6 link-local, que normalmente no tiene routing configurado entre las VMs. El error es silencioso: el driver no genera ningún paquete y la QP se cierra.

### El tráfico RoCEv2 no aparece en la captura de Wireshark

Verificar que la captura se hace en `br-roce` (el bridge) y no en `eth0` (la interfaz de WSL hacia Windows). Verificar que `ibv_rc_pingpong` reporta ancho de banda y latencia (si no lo hace, el tráfico RDMA no se generó).

### Wireshark no muestra campos InfiniBand

Si la captura tiene paquetes UDP:4791 pero Wireshark no activa el disector InfiniBand, forzarlo manualmente: click derecho sobre un paquete UDP:4791 → `Decode As...` → seleccionar `InfiniBand`.

### Rendimiento muy bajo en las VMs

Verificar que QEMU usa KVM y no TCG. El log de arranque de QEMU debe mostrar `KVM: Initialised`. Con TCG el rendimiento es significativamente menor.

### La configuración de red se pierde al reiniciar WSL

La topología de bridge + TAPs no es persistente. Ejecutar `start-topology.sh` (sección 11) después de cada reinicio de WSL, antes de arrancar las VMs.
