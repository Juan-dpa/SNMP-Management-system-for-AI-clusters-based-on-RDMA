# Problemas que han ocurrido durante el desarrollo

## 1. Soft-RoCE depende de un socket UDP creado en el netspace global y no del usuario

Esto ha implicado que durante la implementación de la topología, no se pudiera usar Docker y se haya optado finalmente por virtualización de los workers con QEMU. La virtualización permitía separar los netspace globales, y solucionar de manera directa el problema.

## 2. Implementación de ECN con Soft-RoCE. 

Soft-RoCE no implementa ECN. Los paquetes mandados salen con valor 00 en los dos bits de la cabecera IP que definen a ECN. Este 00 significa NOT ECN CAPABLE, por lo que no es posible el control de la congestión con Soft-RoCE. Lo que si se ha podido hacer es marcar ECN capable en el switch usando:

```bash
sudo ovs-ofctl add-flow br0 -O OpenFlow13 "priority=100,ip,actions=set_field:2->ip_ecn,NORMAL"
```

Esto permite que en dicho switch ya se pueda marcar la congestión con algún criterio de disciplina de colas. En este caso hemos usado RED. 

```bash
for iface in enp0s2 enp0s3 enp0s4; do
    sudo tc qdisc add dev $iface root red \
        limit 100000 min 30000 max 60000 avpkt 1500 \
        bandwidth 1000mbit ecn probability 0.1
done
```

Lo que se consigue con estos comandos es conseguir que los contadores relacionados a ECN aumenten. En ningún momento esto simula ECN real, precisamente porque no hay control de la congestión, al no haber envios de mensajes CNP (notificación al emisor de un paquete marcado como ECN). Esto forma parte del protocolo DCQCN, el cual no implementa Soft-RoCE.

Estos cambios se han colocado en Config_OVS.sh