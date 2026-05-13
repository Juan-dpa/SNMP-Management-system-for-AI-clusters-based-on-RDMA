# 4 — GRAFANA

## Paso 1 — Instalar Grafana en WSL

Ejecuta en WSL:

```bash
sudo apt-get install -y apt-transport-https software-properties-common wget
sudo mkdir -p /etc/apt/keyrings/
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee -a /etc/apt/sources.list.d/grafana.list
sudo apt-get update
sudo apt-get install grafana -y
```

---

## Paso 2 — Configurar el datasource de InfluxDB

Ejecuta en WSL:

```bash
sudo tee /etc/grafana/provisioning/datasources/influxdb.yaml << 'EOF'
apiVersion: 1
datasources:
  - name: InfluxDB-RoCE
    type: influxdb
    access: proxy
    url: http://localhost:8086
    database: roce_cluster
    isDefault: true
    jsonData:
      httpMode: GET
EOF
```

---

## Paso 3 — Configurar el dashboard

### 3.1 — Indicar a Grafana dónde buscar dashboards

```bash
sudo tee /etc/grafana/provisioning/dashboards/dashboards.yaml << 'EOF'
apiVersion: 1
providers:
  - name: 'RoCE Cluster Dashboards'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    options:
      path: /var/lib/grafana/dashboards
EOF
```

### 3.2 — Crear la carpeta de dashboards

```bash
sudo mkdir -p /var/lib/grafana/dashboards
```

### 3.3 — Inyectar el dashboard JSON

Colocar el json el cual se encuentra en el repositorio

```
/var/lib/grafana/dashboards/roce_monitor.json
```

---

## Paso 4 — Arrancar Grafana

```bash
sudo systemctl enable grafana-server
sudo systemctl restart grafana-server
```

---

## Verificación

Abre en Windows: `http://localhost:3000`

- Usuario: `admin`
- Contraseña: `rdma`

Ve a **Dashboards** — el panel "RoCEv2 Cluster Analytics" debe aparecer ya creado y conectado a InfluxDB, mostrando `sent_pps`, `asymmetry_index` y `error_rate` sin ninguna configuración manual adicional.
