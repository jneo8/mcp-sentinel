## Deploy Canonical k8s on lxd with microceph integration

https://gist.github.com/jneo8/fb2731b67349f327de99eb64af7d6b54

## Deploy COS

```sh
juju switch lxd-k8s-ctrl
juju add-model cos
juju deploy cos-lite --trust

juju offer prometheus:receive-remote-write
juju offer grafana:grafana-dashboard
juju offer loki:logging

juju run -m lxd-k8s-ctrl:cos traefik/leader show-proxied-endpoints
juju run -m lxd-k8s-ctrl:cos grafana/leader get-admin-password
```

## 

```sh
juju switch local-lxd
juju deploy grafana-agent
juju relate grafana-agent microceph

juju find-offers lxd-k8s-ctrl:
juju relate grafana-agent lxd-k8s-ctrl:admin/cos.grafana
juju relate grafana-agent lxd-k8s-ctrl:admin/cos.prometheus
juju relate grafana-agent lxd-k8s-ctrl:admin/cos.loki
```
