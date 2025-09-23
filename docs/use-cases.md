# Use cases

# Ceph PG Repair Guide

This document explains how to identify when Ceph Placement Groups (PGs) require repair and provides the steps to perform a repair safely.

---

## 1. Relevant Alerts

When monitoring via Prometheus, the following alerts indicate PG issues that may require manual intervention:

- **CephPGsDamaged**
  Damaged placement groups detected. **Immediate repair required**.

- **CephPGsUnclean**
  PGs not in a clean state. May need recovery or repair if the condition persists.

- **CephPGUnavilableBlockingIO**
  PGs unavailable and blocking I/O. Urgent attention required.

- **CephPGNotScrubbed / CephPGNotDeepScrubbed** 
  PGs have not been scrubbed or deep-scrubbed within the expected interval. This may lead to undetected inconsistencies and eventual need for repair.

---

## 2. Identifying Problematic PGs

List all PGs in non-clean states:

```bash
ceph pg dump | grep -E -v "active+clean"
```
