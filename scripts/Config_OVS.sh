# Ver las interfaces disponibles
ip link show
# Esperamos 4 interfaces (aparte de lo): enp0s2, enp0s3, enp0s4, enp0s5
# El orden depende del orden de los -device en QEMU:
#   enp0s2 = sw1 (→ worker 1)
#   enp0s3 = sw2 (→ worker 2)
#   enp0s4 = sw3 (→ worker 3)
#   enp0s5 = mgmt (→ host)

# Arrancar OVS
sudo systemctl start openvswitch-switch

# Crear bridge OVS
sudo ovs-vsctl add-br br0

# Añadir los 4 puertos
sudo ovs-vsctl add-port br0 enp0s2   # worker 1
sudo ovs-vsctl add-port br0 enp0s3   # worker 2
sudo ovs-vsctl add-port br0 enp0s4   # worker 3
sudo ovs-vsctl add-port br0 enp0s5   # host management

# Levantar interfaces (sin IP — OVS las gestiona)
for iface in enp0s2 enp0s3 enp0s4 enp0s5; do
    sudo ip link set $iface up
done

# IP del switch en el puerto interno de OVS
sudo ip addr add 10.10.0.10/24 dev br0
sudo ip link set br0 up

# Verificar
sudo ovs-vsctl show

# === Port mirroring para Snort ===

# Puerto interno donde Snort escuchará
sudo ovs-vsctl add-port br0 mirror0 -- set interface mirror0 type=internal
sudo ip link set mirror0 up

# Mirror: todo el tráfico de/hacia los 3 workers → mirror0
sudo ovs-vsctl -- set bridge br0 mirrors=@m \
    -- --id=@w1 get port enp0s2 \
    -- --id=@w2 get port enp0s3 \
    -- --id=@w3 get port enp0s4 \
    -- --id=@dst get port mirror0 \
    -- --id=@m create mirror name=snort-mirror \
       select-src-port=@w1,@w2,@w3 select-dst-port=@w1,@w2,@w3 output-port=@dst

# Verificar el mirror
sudo ovs-vsctl list mirror

# Fuerza que el trafico RoCE sea ECN ENABLED

sudo ovs-ofctl add-flow br0 -O OpenFlow13 "priority=100,ip,actions=set_field:2->ip_ecn,NORMAL"

# Politicas de disciplina de cola RED, para marcar CE en cabeceras IP.

for iface in enp0s2 enp0s3 enp0s4; do
    sudo tc qdisc add dev $iface root red \
        limit 100000 min 30000 max 60000 avpkt 1500 \
        bandwidth 1000mbit ecn probability 0.1
done
