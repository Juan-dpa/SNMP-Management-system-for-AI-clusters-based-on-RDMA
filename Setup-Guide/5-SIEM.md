# Componente SIEM del sistema

## Índice

1. Requisitos 
2. Explicación
3. Descarga de Kali

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

```bash
user@switch:~$ sudo sed -i 's/DEBIAN_SNORT_INTERFACE="enp0s2"/DEBIAN_SNORT_INTERFACE="mirror0"/g' /etc/snort/snort.debian.conf
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

