# Pequeña guía para añadir TRAPs 

## Índice

1. Requisitos Previos
2. Explicación
3. Implementación

## 1. Requisitos Previos

Se debe haber modificado Config_OVS.sh en los workers, para que el trafico sea ECN allowed.

## 2. Explicación

Interesa bastante añadir la capacidad de mandar TRAPs desde los agentes SNMP. Hemos considerado que los paquetes marcados con ECN, según lo indica la RFC 3168, son clave para el sistema. RoCE no contiene control de la congestión al funcionar sobre UDP. Los mensajes CNP que "sirven de asentimiento" al emisor (en relación a un paquete recibido marcado con ECN) no son emulables desde Soft-RoCE. Consideramos ECN como una implementación de TRAP mas que suficiente.

## 3. Implementación

### Agentes

Abrir el fichero de configuración snmpd

```bash
sudo nano /etc/snmp/snmpd.conf
```

Y dejarlo tal que así (el cambio principal es que se define el destino de los TRAPs)

```conf
agentAddress udp:161
rocommunity public 10.10.0.254
rocommunity public localhost
pass_persist .1.3.6.1.4.1.99999 /usr/local/bin/roce_agent.py

# --- DESTINO DE TRAPS ---
trap2sink 10.10.0.254:1162 public
```

Posteriormente, modificar el roce-agent.py de cada worker al estado actual del repositorio. El umbral usado en código se corresponde con medidas empíricas, obtenidas directamente desde un worker.

```bash
for i in $(seq 1 6); do
    awk '/^IpExt:/ {if(h=="") {for(i=1;i<=NF;i++) name[i]=$i; h=1; next} for(i=1;i<=NF;i++) if(name[i]=="InCEPkts") printf "InCEPkts: %s\n",$i}' /proc/net/netstat
    sleep 10
done
InCEPkts: 3872
InCEPkts: 3922
InCEPkts: 3938
InCEPkts: 3944
InCEPkts: 3995
InCEPkts: 4042
```

La media es de 34 CEs para muestras de 10s. 

Para modificar, simplemente vaciar, abrir y copiar en nano:

```bash
> /usr/local/bin/roce_agent.py
sudo nano /usr/local/bin/roce_agent.py
sudo systemctl restart snmpd
```

### Gestor

El gestor escuchará mensajes SNMP al puerto destino 1162. Esto evita conflictos con el puerto reservado 162, el cual ya es usado por snmpdtrap. 

Solo es necesario cambiar el codigo del gestor al estado actual del repositorio y ejecutarlo.

Finalmente, comprobar que se está escribiendo en InfluxDB.

```bash
influx -database 'roce_cluster' -execute 'SELECT * FROM roce_traps' -precision rfc3339
```