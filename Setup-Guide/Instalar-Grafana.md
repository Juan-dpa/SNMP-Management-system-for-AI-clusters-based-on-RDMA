### **PASO 1: Instalar Grafana en WSL**

Copia y pega todo el código en un terminal wsl:

sudo apt-get install \-y apt-transport-https software-properties-common wget  
sudo mkdir \-p /etc/apt/keyrings/  
wget \-q \-O \- https://apt.grafana.com/gpg.key | gpg \--dearmor | sudo tee /etc/apt/keyrings/grafana.gpg \> /dev/null  
echo "deb \[signed-by=/etc/apt/keyrings/grafana.gpg\] https://apt.grafana.com stable main" | sudo tee \-a /etc/apt/sources.list.d/grafana.list  
sudo apt-get update  
sudo apt-get install grafana \-y

---

### **PASO 2: Automatizar la conexión a InfluxDB (Datasources Provisioning)**

Copia y pega todo el código en un terminal wsl:

sudo tee /etc/grafana/provisioning/datasources/influxdb.yaml \<\< 'EOF'  
apiVersion: 1  
datasources:  
  \- name: InfluxDB-RoCE  
    type: influxdb  
    access: proxy  
    url: http://localhost:8086  
    database: roce\_cluster  
    isDefault: true  
    jsonData:  
      httpMode: GET  
EOF

---

### **PASO 3: Automatizar el Dashboard (Dashboards Provisioning)**

Ahora le diremos a Grafana que busque dashboards prefabricados en una carpeta específica de tu sistema.

**1\. Creamos el archivo que le indica a Grafana dónde buscar:**

Copia y pega en el terminal wsl:

sudo tee /etc/grafana/provisioning/dashboards/dashboards.yaml \<\< 'EOF'  
apiVersion: 1  
providers:  
  \- name: 'RoCE Cluster Dashboards'  
    orgId: 1  
    folder: ''  
    type: file  
    disableDeletion: false  
    updateIntervalSeconds: 10  
    options:  
      path: /var/lib/grafana/dashboards  
EOF

**2\. Creamos la carpeta contenedora:**

Copia y pega en el terminal wsl:

sudo mkdir \-p /var/lib/grafana/dashboards

**3\. Inyectamos el Dashboard JSON:** Los dashboards de Grafana son archivos JSON muy extensos. He preparado uno compacto que extrae las métricas exactas que tienes en tu InfluxDB (sent\_pps, asymmetry\_index, error\_rate).

Copia todo este bloque gigante y pégalo en la terminal (creará el dashboard automáticamente):

Bash  
sudo tee /var/lib/grafana/dashboards/roce\_monitor.json \<\< 'EOF'  
{  
  "title": "RoCEv2 Cluster Analytics \- Profesional",  
  "refresh": "5s",  
  "schemaVersion": 36,  
  "timezone": "browser",  
  "panels": \[  
    {  
      "title": "Tráfico RDMA por Worker (pps)",  
      "type": "timeseries",  
      "gridPos": { "h": 10, "w": 12, "x": 0, "y": 0 },  
      "targets": \[  
        {  
          "measurement": "roce\_worker",  
          "query": "SELECT mean(\\"sent\_pps\\") FROM \\"roce\_worker\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"worker\\" fill(null)",  
          "rawQuery": true,  
          "alias": "Enviados $tag\_worker"  
        },  
        {  
          "measurement": "roce\_worker",  
          "query": "SELECT mean(\\"rcvd\_pps\\") FROM \\"roce\_worker\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"worker\\" fill(null)",  
          "rawQuery": true,  
          "alias": "Recibidos $tag\_worker"  
        }  
      \],  
      "fieldConfig": { "defaults": { "custom": { "drawStyle": "line", "lineInterpolation": "linear", "spanNulls": true } } }  
    },  
    {  
      "title": "Asimetría del Cluster (Bottlenecks)",  
      "type": "timeseries",  
      "gridPos": { "h": 10, "w": 12, "x": 12, "y": 0 },  
      "targets": \[  
        {  
          "measurement": "cluster",  
          "query": "SELECT mean(\\"asymmetry\_index\\") FROM \\"cluster\\" WHERE $timeFilter GROUP BY time($\_\_interval) fill(null)",  
          "rawQuery": true,  
          "alias": "Asimetria"  
        },  
        {  
          "measurement": "cluster",  
          "query": "SELECT mean(\\"max\_min\_spread\\") FROM \\"cluster\\" WHERE $timeFilter GROUP BY time($\_\_interval) fill(null)",  
          "rawQuery": true,  
          "alias": "Spread"  
        },  
        {  
          "measurement": "cluster",  
          "query": "SELECT mean(\\"mean\_pkt\_rate\\") FROM \\"cluster\\" WHERE $timeFilter GROUP BY time($\_\_interval) fill(null)",  
          "rawQuery": true,  
          "alias": "Media Pkts"  
        }  
      \],  
      "fieldConfig": {  
        "defaults": { "custom": { "spanNulls": true } },  
        "overrides": \[ { "matcher": { "id": "byName", "options": "Asimetria" }, "properties": \[ { "id": "custom.axisPlacement", "value": "right" } \] } \]  
      }  
    },  
    {  
      "title": "Ratio Tráfico RDMA vs OVS (Salud)",  
      "type": "timeseries",  
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 10 },  
      "targets": \[  
        {  
          "measurement": "roce\_worker",  
          "query": "SELECT mean(\\"rdma\_vs\_ovs\_ratio\\") FROM \\"roce\_worker\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"worker\\" fill(null)",  
          "rawQuery": true,  
          "alias": "Ratio $tag\_worker"  
        }  
      \],  
      "fieldConfig": { "defaults": { "custom": { "spanNulls": true } } }  
    },  
    {  
      "title": "Tasa de Errores RDMA (error\_rate)",  
      "type": "timeseries",  
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 10 },  
      "targets": \[  
        {  
          "measurement": "roce\_worker",  
          "query": "SELECT mean(\\"error\_rate\\") FROM \\"roce\_worker\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"worker\\" fill(null)",  
          "rawQuery": true,  
          "alias": "Errores $tag\_worker"  
        },  
        {  
          "measurement": "roce\_worker",  
          "query": "SELECT mean(\\"retransmission\_ratio\\") FROM \\"roce\_worker\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"worker\\" fill(null)",  
          "rawQuery": true,  
          "alias": "Retransmisiones $tag\_worker"  
        },  
        {  
          "measurement": "roce\_worker",  
          "query": "SELECT mean(\\"ecn\_ratio\\") FROM \\"roce\_worker\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"worker\\" fill(null)",  
          "rawQuery": true,  
          "alias": "ECN $tag\_worker"  
        }  
      \],  
      "fieldConfig": { "defaults": { "custom": { "spanNulls": true } } }  
    },  
    {  
      "title": "Rendimiento Puerto OVS",  
      "type": "timeseries",  
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 18 },  
      "targets": \[  
        {  
          "measurement": "ovs\_port",  
          "query": "SELECT mean(\\"port\_throughput\_mbps\\") FROM \\"ovs\_port\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"port\\" fill(null)",  
          "rawQuery": true,  
          "alias": "Mbps puerto $tag\_port"  
        },  
        {  
          "measurement": "ovs\_port",  
          "query": "SELECT mean(\\"port\_drop\_rate\\") FROM \\"ovs\_port\\" WHERE $timeFilter GROUP BY time($\_\_interval), \\"port\\" fill(null)",  
          "rawQuery": true,  
          "alias": "Drops puerto $tag\_port"  
        }  
      \],  
      "fieldConfig": {  
        "defaults": { "custom": { "spanNulls": true } },  
        "overrides": \[ { "matcher": { "id": "byRegexp", "options": "/^Drops.\*/" }, "properties": \[ { "id": "custom.axisPlacement", "value": "right" } \] } \]  
      }  
    },  
    {  
      "title": "Worker más lento (Straggler)",  
      "type": "stat",  
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 18 },  
      "targets": \[  
        {  
          "measurement": "cluster",  
          "query": "SELECT last(\\"straggler\_id\\") FROM \\"cluster\\" WHERE $timeFilter GROUP BY time($\_\_interval)",  
          "rawQuery": true  
        }  
      \],  
      "options": {  
        "reduceOptions": { "calcs": \["lastNotNull"\], "fields": "/.\*/", "values": false },  
        "textMode": "value",  
        "colorMode": "value"  
      }  
    }  
  \]  
}  
EOF

---

### **PASO 4: ¡Arrancar el sistema\!**

Con los archivos de aprovisionamiento en su sitio, arranca (o reinicia) Grafana para que lea toda tu magia:

Copia y pega en el terminal wsl:

sudo systemctl enable grafana-server  
sudo systemctl restart grafana-server

### **El resultado final**

1. Abre tu navegador web en Windows y ve a: [**http://localhost:3000**](http://localhost:3000) **O [http://localhost:300](http://localhost:3000)0/login**  
2. El usuario es **admin** y la contraseña es **rdma**.  
3. Ve directamente a la sección de **Dashboards**. ¡Verás que tu panel "RoCEv2 Cluster Analytics" ya está creado, conectado a InfluxDB y dibujando los paquetes por segundo, la asimetría y los errores sin haber tocado un solo botón en la interfaz\!

