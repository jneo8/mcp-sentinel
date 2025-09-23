# LXD VM Hot Attach/Detach Storage Guide

This guide explains how to dynamically attach and detach storage volumes to running LXD virtual machines without stopping them.

## Prerequisites

- LXD installed and configured
- A running VM
- Storage pool available
- VM guest OS with hot-plug support (most modern Linux distributions)

## Hot Attach Storage Volume

### Step 1: Create a Storage Volume (if needed)

```bash
# Create a new storage volume
lxc storage volume create <pool-name> <volume-name> --type=block size=<size>

# Example: Create a 10GB volume
lxc storage volume create default data-volume --type=block size=10GB
```

### Step 2: Hot Attach the Volume

```bash
# Attach volume to running VM
lxc config device add <vm-name> <device-name> disk pool=<pool-name> source=<volume-name>

# Example: Attach data-volume as disk1
lxc config device add my-vm disk1 disk pool=default source=data-volume
```

### Step 3: Verify Attachment

```bash
# Check device configuration
lxc config device list my-vm

# Inside the VM, verify new disk appears
lxc exec my-vm -- lsblk
```

### Step 4: Format and Mount (Inside VM)

```bash
# Enter the VM
lxc exec my-vm -- bash

# Format the new disk (example: /dev/sdb)
mkfs.ext4 /dev/sdb

# Create mount point
mkdir /mnt/data

# Mount the disk
mount /dev/sdb /mnt/data

# Add to fstab for persistent mounting
echo '/dev/sdb /mnt/data ext4 defaults 0 2' >> /etc/fstab
```

## Hot Detach Storage Volume

### Step 1: Unmount Inside VM

```bash
# Enter the VM
lxc exec my-vm -- bash

# Unmount the volume
umount /mnt/data

# Remove from fstab if added
sed -i '/\/dev\/sdb/d' /etc/fstab
```

### Step 2: Hot Detach the Volume

```bash
# Detach the device from VM
lxc config device remove my-vm disk1
```

### Step 3: Verify Detachment

```bash
# Check device configuration
lxc config device list my-vm

# Inside the VM, verify disk is gone
lxc exec my-vm -- lsblk
```

## Directory Mount Hot Attach/Detach

### Hot Attach Directory

```bash
# Attach host directory to VM
lxc config device add my-vm shared disk source=/host/shared/path path=/vm/shared/path

# Example
lxc config device add my-vm shared-data disk source=/home/user/shared path=/mnt/shared
```

### Hot Detach Directory

```bash
# Detach directory mount
lxc config device remove my-vm shared-data
```

## Troubleshooting

### Check VM Hot-Plug Support

```bash
# Inside the VM, check for ACPI hot-plug support
dmesg | grep -i acpi
ls /sys/bus/acpi/devices/
```

### Common Issues

1. **Device not appearing in VM:**
   - Check if guest OS supports hot-plug
   - Verify ACPI is enabled in VM
   - Try rescanning SCSI bus: `echo "- - -" > /sys/class/scsi_host/host*/scan`

2. **Permission errors:**
   - Ensure proper security profiles are set
   - Check storage pool permissions

3. **Mount failures:**
   - Verify filesystem type
   - Check disk is properly formatted
   - Ensure mount point exists

### Useful Commands

```bash
# List all storage pools
lxc storage list

# List volumes in a pool
lxc storage volume list default

# Show volume details
lxc storage volume show default data-volume

# List all VM devices
lxc config device list my-vm

# Show VM configuration
lxc config show my-vm
```

## Limitations

- Root disk cannot be hot-detached
- Some storage drivers may not support hot operations
- Windows VMs may require additional drivers
- Always unmount properly before detaching to prevent data loss

## Best Practices

1. Always unmount volumes inside the VM before detaching
2. Update `/etc/fstab` when adding persistent storage
3. Test hot-plug operations in non-production environments first
4. Monitor VM logs during hot operations: `lxc info my-vm --show-log`
5. Use meaningful device names for easier management