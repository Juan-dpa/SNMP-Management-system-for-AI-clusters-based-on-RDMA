[6-TELEGRAM-ALERTAS.md](http://6-TELEGRAM-ALERTAS.md)

Prerrequisitos
-  Tener 5-SIEM.md terminado correctamente
-  Tener vm1, vm2, vm3 y switch abiertos y funcionando(start-traffic.sh, Config_OVS.sh, Network_Topology.sh)

PASO 1  
Clonar el repositorio o copiar y pegar los siguientes archivos:

- [config.py](http://config.py)  
- telegram\_alert.py  
- syslog\_alert\_manager.py 

PASO 2 \- Habilitar conexión sin contraseña  
Copiar y pegar esto en WSL y darle enter a todo:  
ssh-keygen \-t rsa \-N ""  
ssh-copy-id user@10.10.0.10

PASO 3- BORRAR REGLAS DE PRIORIDAD 100  
Copia y pega esto en el switch:  
sudo ovs-ofctl del-flows br0 "ip,nw\_dst=10.10.0.1"  
sudo ovs-ofctl del-flows br0 "ip,nw\_dst=10.10.0.2"  
sudo ovs-ofctl del-flows br0 "ip,nw\_dst=10.10.0.3"  
exit

Comprobar qué después al hacer ssh user@10.10.0.10 no pide nada y se conecta directamente

PROBAR:

- [main.py](http://main.py) funciona  
- se manden a Telegram las alertas de kali(wsl \-d kali-linux para abrirlo en PowerShell)  
- funcionan los botones de Ignorar, Limitar y Bloquear de forma visual con grafana.



VUELTA A NORMALIDAD   
Entra al switch desde wsl:  
ssh user@10.10.0.10

Elimina bloqueos:  
sudo ovs-ofctl del-flows br0 "ip,nw\_dst=10.10.0.1"  
sudo ovs-ofctl del-flows br0 "ip,nw\_dst=10.10.0.2"  
sudo ovs-ofctl del-flows br0 "ip,nw\_dst=10.10.0.3"

Elimina límites de tráfico:  
sudo ovs-vsctl set interface enp0s2 ingress\_policing\_rate=0 ingress\_policing\_burst=0  
sudo ovs-vsctl set interface enp0s3 ingress\_policing\_rate=0 ingress\_policing\_burst=0  
sudo ovs-vsctl set interface enp0s4 ingress\_policing\_rate=0 ingress\_policing\_burst=0  
