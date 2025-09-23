# Ceph Alert Simulation Lab (Juju MicroCeph)

Step-by-step guide to simulate and test Ceph alerts in a Juju MicroCeph environment.

---

## Prerequisites

- Deploy MicroCeph based on [build-testing-environment.md](build-testing-environment.md)
- Juju MicroCeph cluster: 3 units, 9 OSDs (3 per unit)
- Prometheus monitoring configured
- Backup before testing: `juju export-bundle --filename pre-test.yaml`

**Current Setup:**
- Units: `microceph/0`, `microceph/1`, `microceph/2`
- OSDs: `1-3` (unit 0), `4-6` (unit 2), `7-9` (unit 1)
- Storage: Loop devices managed by MicroCeph snap

---

## Alert Simulations

### `CephOSDDown` and `CephOSDDownHigh`
**Method:** Manually SSH into MicroCeph node and kill OSD process

**This will make the `ceph_osd_up` metric become 0, which fires the `CephOSDDownHigh` alert.**

```bash
# 1. Stop OSD process
juju ssh microceph/0 -- "sudo pkill -f 'ceph-osd.*--id 3'"

# 2. Verify OSD shows as down but no process exists
juju ssh microceph/0 -- "sudo ceph osd tree | grep osd.3"
juju ssh microceph/0 -- "ps aux | grep 'ceph-osd.*--id 3'"

# 3. Check Prometheus metrics (wait 5-10 minutes)
curl -s "http://10.100.100.12/cos-prometheus-0/api/v1/query?query=ceph_osd_up" | jq '.data.result[])'

# 4. Verify alert fires using amtool
amtool alert --alertmanager.url http://10.100.100.12/cos-alertmanager | grep CephOSDDown

# 5. For CephOSDDownHigh, simulate multiple OSDs down (kill another OSD)
juju ssh microceph/1 -- "sudo pkill -f 'ceph-osd.*--id 7'"

# 6. Check CephOSDDownHigh alert using amtool (wait 10-15 minutes)
amtool alert --alertmanager.url http://10.100.100.12/cos-alertmanager | grep CephOSDDownHigh
```

---

## Recovery

### CephOSDDown Recovery
```bash
# Restart services to bring OSDs back up
juju ssh microceph/0 -- "sudo snap restart microceph.osd"
juju ssh microceph/1 -- "sudo snap restart microceph.osd"

# Verify
juju ssh microceph/0 -- "sudo ceph osd tree"
juju ssh microceph/0 -- "sudo ceph -s"
```

---

## Operator Response Checklist

When alerts fire, follow this diagnosis:

### Quick Assessment
```bash
juju ssh microceph/0 -- sudo ceph -s
juju ssh microceph/0 -- sudo ceph health detail
juju ssh microceph/0 -- sudo ceph osd tree
```

### PG Analysis
```bash
juju ssh microceph/0 -- sudo ceph pg stat
juju ssh microceph/0 -- sudo ceph pg ls | grep -v "active+clean"
```

### Logs
```bash
juju ssh microceph/0 -- sudo ceph log last 20
juju ssh microceph/0 -- sudo ceph -w  # Real-time monitoring
```

---

## Validation & Rollback

### Verify Recovery
```bash
juju ssh microceph/0 -- sudo ceph -s
juju ssh microceph/0 -- sudo ceph osd tree
juju status
```

### Emergency Rollback
```bash
# Nuclear option: Restore from backup
juju destroy-model workload --destroy-storage -y
juju add-model workload
juju deploy pre-test.yaml
```

---

## Key Notes

- **Kill OSD process**: Simple method to simulate CephOSDDown alert
- **Alert delays**: Most alerts have 5-minute delays to prevent false positives
- **Metrics lag**: Prometheus metrics may take several minutes to update
- **MicroCeph specifics**: Uses loop devices, managed by snap, OSDs may renumber after re-add
- **Do not use in production**
