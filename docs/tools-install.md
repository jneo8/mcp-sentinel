# Prometheus Tools Installation

## promtool
Download from: https://prometheus.io/download/
```bash
tar -xzf prometheus-*.tar.gz
sudo cp prometheus-*/promtool /usr/local/bin/
```

## amtool
```bash
go install github.com/prometheus/alertmanager/cmd/amtool@latest
```

## Usage
```bash
# Query alerts from Prometheus
promtool query instant 'ALERTS' --server=http://prometheus-url:9090

# Query alerts from Alertmanager
amtool alert query --alertmanager.url=http://alertmanager-url:9093
```