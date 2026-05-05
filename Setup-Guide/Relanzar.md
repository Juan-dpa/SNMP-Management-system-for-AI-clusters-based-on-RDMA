# Relanzar el sistema

## 1. Requisitos previos

Se deben haber finalizado: 1-Topology.md y 2-Management.md 

## 2. Ejecutar comandos de lanzamiento 

Cada VM se arranca en una terminal WSL distinta.

### Workers

```bash
# Worker 1
sudo qemu-system-x86_64 -name vm1 -machine q35,accel=kvm -cpu host -m 2048 -smp 2 \
    -drive file=$HOME/qemu-roce/vm1.qcow2,format=qcow2,if=virtio \
    -drive file=$HOME/qemu-roce/seed-vm1.iso,format=raw,if=virtio \
    -netdev tap,id=net0,ifname=tap-w1,script=no,downscript=no \
    -device virtio-net-pci,netdev=net0,mac=52:54:00:00:00:01 \
    -nographic -serial mon:stdio

# Worker 2
sudo qemu-system-x86_64 -name vm2 -machine q35,accel=kvm -cpu host -m 2048 -smp 2 \
    -drive file=$HOME/qemu-roce/vm2.qcow2,format=qcow2,if=virtio \
    -drive file=$HOME/qemu-roce/seed-vm2.iso,format=raw,if=virtio \
    -netdev tap,id=net0,ifname=tap-w2,script=no,downscript=no \
    -device virtio-net-pci,netdev=net0,mac=52:54:00:00:00:02 \
    -nographic -serial mon:stdio

# Worker 3
sudo qemu-system-x86_64 -name vm3 -machine q35,accel=kvm -cpu host -m 2048 -smp 2 \
    -drive file=$HOME/qemu-roce/vm3.qcow2,format=qcow2,if=virtio \
    -drive file=$HOME/qemu-roce/seed-vm3.iso,format=raw,if=virtio \
    -netdev tap,id=net0,ifname=tap-w3,script=no,downscript=no \
    -device virtio-net-pci,netdev=net0,mac=52:54:00:00:00:03 \
    -nographic -serial mon:stdio
```

### Switch (4 NICs: 3 data + 1 gestión)

```bash
sudo qemu-system-x86_64 -name switch -machine q35,accel=kvm -cpu host -m 2048 -smp 2 \
    -drive file=$HOME/qemu-roce/switch.qcow2,format=qcow2,if=virtio \
    -drive file=$HOME/qemu-roce/seed-switch.iso,format=raw,if=virtio \
    -netdev tap,id=sw1,ifname=tap-s1,script=no,downscript=no \
    -device virtio-net-pci,netdev=sw1,mac=52:54:00:00:00:11 \
    -netdev tap,id=sw2,ifname=tap-s2,script=no,downscript=no \
    -device virtio-net-pci,netdev=sw2,mac=52:54:00:00:00:12 \
    -netdev tap,id=sw3,ifname=tap-s3,script=no,downscript=no \
    -device virtio-net-pci,netdev=sw3,mac=52:54:00:00:00:13 \
    -netdev tap,id=mgmt,ifname=tap-sm,script=no,downscript=no \
    -device virtio-net-pci,netdev=mgmt,mac=52:54:00:00:00:10 \
    -nographic -serial mon:stdio
```

## 3. Lanzar script de configuración OVS en switch

Dentro de la terminal correspondiente a la máquina virtual del switch, ejecutar:

```bash
user@switch:~$ ./Config_OVS.sh
```

## 4. Lanzar script de configuración taps WSL

```bash
$:~/Proyecto_Gestion/scripts$ ./Network_Topology.sh
```

## 5. Relanzar las interfaces Soft-RoCe de cada VM

Desde WSL, comprobar que `rxe0` existe en los 3 workers:

```bash
for ip in 10.10.0.1 10.10.0.2 10.10.0.3; do
    echo "--- $ip ---"
    ssh user@$ip "rdma link"
done
```

Si `rxe0` no aparece en alguno, recrearlo:

```bash
ssh user@10.10.0.1 "sudo modprobe rdma_rxe && sudo rdma link add rxe0 type rxe netdev enp0s2"
ssh user@10.10.0.2 "sudo modprobe rdma_rxe && sudo rdma link add rxe0 type rxe netdev enp0s2"
ssh user@10.10.0.3 "sudo modprobe rdma_rxe && sudo rdma link add rxe0 type rxe netdev enp0s2"
```

## 6. Arrancar tráfico

Dentro de WSL, ejecutar:

```bash
$:~/Proyecto_Gestion/scripts$ ./start-traffic.sh
```

## 7. Iniciar el Gestor

```bash
$:~/Proyecto_Gestion/src/snmp_manager$ python3 main.py
```