# Componente SIEM del sistema

## Índice

1. Requisitos 
2. Explicación
3. Descarga de Kali
4. Implementación

## 1. Requisitos

Se debe tener en funcionamiento toda la componente de gestión, tener instalado snort en el switch y espacio para instalar Kali WSL.

## 2. Explicación

El objetivo es demostrar que el sistema SIEM (Security Information and Event Management) sea capaz de detectar intentos de intrusión o trafico post-explotación. Para ello, se va a usar SNORT. El gestor actual deberá ser capaz de leer logs de SNORT, y generar alertas por Telegram, permitiendo cortar el tráfico de la interfaz del worker comprometido.

### Fases de Ataques

Para emular ambas fases se va a usar lo siguiente:

1. Kali WSL para emular intrusión. Es especialmente comoda puesto que todas las imágenes WSL comparten el mismo espacio de red, por lo que por defecto se puede mandar trafico a Ubuntu sin configuración alguna. Se usarán 2 técnicas, NMAP (Escaneo de puertos) e Hydra (SSH por fuerza bruta).

2. Script que emulará un C2 (Command and Control) desde el Worker afectado. 

### Gestor

Para leer los logs generados por el IDS, se usará Syslog. Snort implementa esta funcionalidad de manera simple. El gestor tendrá un hilo leyendo por syslog, mandará alertas y escuchará sus respuestas por la API de Telegram y tendrá en cuenta el "spam" de logs (mandará alerta sobre un flujo UDP/IP cada 5 minutos). Tras obtener las respuestas debe ser capaz de cortar el trafico para el worker atacado.

### Inciso

Antes de desarrollar nada, se debe tener en cuenta de que hay ciertos resquicios del proyecto a limpiar:

1. El traffic_controller.py distingue por worker id. En caso de ser el tercer worker el patrón de tráfico es algo distinto. Esto es completamente absurdo, pero tenía sentido cuando la idea de seguridad no estaba tan clara. Se debe eliminar esta distinción, para algo así ya esta el script post-explotación a desarrollar.

2. Snort tiene el port mirroring en la interfaz del worker 3. Siempre se ha asumido que el worker 3 será el atacado, pero en un entorno real nunca se va a usar el IDS para un solo worker, logicamente.

Dichos cambios han sido reflejados en traffic_controller.py y Config_OVS.sh

Finalmente, colocar a snort en la interfaz mirror0.

```bash
user@switch:~$ sudo sed -i 's/DEBIAN_SNORT_INTERFACE="enp0s2"/DEBIAN_SNORT_INTERFACE="mirror0"/g' /etc/snort/snort.debian.conf
sudo systemctl disable snort
```

## 3. Descarga de Kali

```powershell
wsl --install -d kali-linux
```

Generar usuario/contraseña

```bash
sudo apt update
sudo apt install -y nmap hydra dnsutils inetutils-ping
```

Comprobar conexión con uno de los workers, por ejemplo:

```bash
ping -c 3 10.10.0.3
```

Si se busca añadir GUI (recomendado), seguir la guía [text](https://www.kali.org/docs/wsl/win-kex/#optional-steps)

## 4. Implementación

### SNORT

Vamos primero a procedes con una prueba sencilla de IDS. Para empezar:

```bash
sudo systemctl stop snort
sudo snort -c /etc/snort/snort.conf -i mirror0 -A console
```

Estos comandos nos dejan ver las alertas de snort, directamente en el terminal del switch. Continuando, vamos a hacer un reconocimiento de puertos con nmap y ver la salida.

Desde Kali:

```bash
sudo nmap -sS -p- -T4 10.10.0.3
```

Si aparecen alertas en Snort, está funcionando.

Ahora, en cuanto a los logs, se debe indicar a Snort que use Syslog.

```bash
sudo nano /etc/snort/snort.conf
```

Ctrl+W y buscar: output alert_ y descomentar la siguiente línea:

```
output alert_syslog: LOG_AUTH LOG_ALERT
```

Posteriormente se debe reiniciar snort y verificar que se loggean las alertas para poder usar Syslog.

```bash
sudo systemctl restart snort
sudo systemctl status snort
sudo tail -f /var/log/auth.log | grep -i snort
```

Y lanzar el comando de NMAP anteriomente usado, en la WSL Kali.

### SYSLOG

```bash
sudo nano /etc/rsyslog.d/60-snort-forward.conf
```

Copiar y pegar:

```
# Enviar alertas de Snort al Gestor en el Host WSL por UDP (puerto 1514)
:programname, startswith, "snort" @10.10.0.254:1514

# Evitar que se sigan procesando (opcional, para no llenar auth.log localmente)
& stop
```

```bash
sudo systemctl restart rsyslog
```

Ahora, desde el Host WSL:

```bash
nc -u -l -p 1514
```

Finalmente lanzar el comando NMAP que hemos usado anteriormente, y ver la salida en el terminal host. Si todo está correctamente configurado, deberán aparecer las alertas. Esto implica que ya podemos proceder a implementar cambios en el gestor.

### Reglas ET (Emerging Threats)

Es un conjunto de reglas mantenido por Proofpoint y la comunidad de ciberseguridad. Se actualiza a diario y tiene firmas espectaculares para detectar malware moderno, C2 (Command & Control), mineros de criptomonedas y herramientas de hacking (como Nmap o Hydra).

La idea es que el set de reglas que trae Snort 2.9 por defecto es extremadamente débil. Los siguientes pasos muestran cómo integrarlas. Dentro del host WSL.

```bash
cd /tmp

# Descargar las reglas de ET Open para Snort
wget https://rules.emergingthreats.net/open/snort-2.9.0/emerging.rules.tar.gz
# 1. Enviar el archivo comprimido a la carpeta temporal del Switch
scp emerging.rules.tar.gz user@10.10.0.10:/tmp/

# 2. Conectarse por SSH y ejecutar todo el proceso de configuración
ssh user@10.10.0.10 << 'EOF'
  echo "--- 1. Descomprimiendo reglas ---"
  cd /tmp
  tar -zxf emerging.rules.tar.gz

  echo "--- 2. Copiando reglas al directorio de Snort ---"
  sudo cp /tmp/rules/*.rules /etc/snort/rules/

  echo "--- 3. Modificando snort.conf ---"
  # Este comando comprueba si las reglas ya están añadidas para no duplicarlas
  if ! grep -q "emerging-scan.rules" /etc/snort/snort.conf; then
      sudo tee -a /etc/snort/snort.conf > /dev/null << 'RULES'

# --- Reglas ET Open añadidas automáticamente ---
include $RULE_PATH/emerging-scan.rules
include $RULE_PATH/emerging-malware.rules
include $RULE_PATH/emerging-botcc.rules
include $RULE_PATH/emerging-current_events.rules
RULES
      echo "Includes añadidos correctamente."
  else
      echo "Los includes ya existían en snort.conf."
  fi

  echo "--- 4. Reiniciando Snort ---"
  sudo systemctl restart snort
  
  echo "--- ESTADO DE SNORT ---"
  sudo systemctl status snort --no-pager | grep Active
EOF
```

Dentro del Switch, se requiere modificar la variable externa IP que define multiples reglas, el tráfico que se va a recibir de la red Hyper-V WSL forma parte de la local (10.10.0.254/24).

```bash
sudo sed -i 's/^ipvar EXTERNAL_NET.*/ipvar EXTERNAL_NET any/' /etc/snort/snort.conf
sudo nano /etc/snort/snort.debian.conf
```

Y pegar cambiar a esta configuración:

```
DEBIAN_SNORT_STARTUP="boot"
DEBIAN_SNORT_HOME_NET="10.10.0.0/24"
DEBIAN_SNORT_OPTIONS=""
DEBIAN_SNORT_INTERFACE="mirror0"
DEBIAN_SNORT_SEND_STAT="false"
DEBIAN_SNORT_STATS_RCPT="root"
DEBIAN_SNORT_STATS_THRESHOLD="1"
```

```bash
sudo systemctl restart snort
```

### Prueba Final

Con Hydra. Vamos a hacer un ataque agresivo, y ver si Snort lo detecta y el Gestor recibe por Syslog la alerta.

En Kali:

```bash
seq -f "user%03g" 1 50 > users.txt
seq -f "pass%03g" 1 200 > passwords.txt
hydra -L users.txt -P passwords.txt -t 16 -V ssh://10.10.0.3
```

En la terminal del gestor, se debe apreciar:

```
10:44:59 [WARNING] syslog_alert_manager — Alerta Snort recibida: attack=DBG SSH SYN to target signature=1:9900001:1 protocol=TCP source=10.10.0.254:46390 victim=10.10.0.3:22 worker=vm3 ovs_port=3
10:44:59 [INFO   ] syslog_alert_manager — TODO Telegram/mitigación pendiente: <33>May 11 08:45:01 switch snort[3268]: [1:9900001:1] DBG SSH SYN to target {TCP} 10.10.0.254:46390 -> 10.10.0.3:22
```

Con NMAP, de igual manera en Kali:

```bash
sudo nmap -sS -T4 10.10.0.3
```

Y se verifica:

10:47:11 [WARNING] syslog_alert_manager — Alerta Snort recibida: attack=ET SCAN Suspicious inbound to PostgreSQL port 5432 [Classification: Potentially Bad Traffic] [Priority: 2] signature=1:2010939:3 protocol=TCP source=10.10.0.254:39741 victim=10.10.0.3:5432 worker=vm3 ovs_port=3
10:47:11 [INFO   ] syslog_alert_manager — TODO Telegram/mitigación pendiente: <33>May 11 08:47:12 switch snort[3268]: [1:2010939:3] ET SCAN Suspicious inbound to PostgreSQL port 5432 [Classification: Potentially Bad Traffic] [Priority: 2] {TCP} 10.10.0.254:39741 -> 10.10.0.3:5432