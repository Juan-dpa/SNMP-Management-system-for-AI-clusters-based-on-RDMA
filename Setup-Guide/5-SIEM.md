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

Vamos primero a procedes con una prueba sencilla de IDS. Para empenzar:

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