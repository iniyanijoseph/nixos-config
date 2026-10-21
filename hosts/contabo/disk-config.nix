# Describes the already-installed disk layout for NixOS.
# WARNING: running disko's formatting/install commands will ERASE this VPS disk.
{ ... }:
{
  disko.devices.disk.system = {
    type = "disk";
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0";
    content = {
      type = "gpt";
      partitions = {
        bios = {
          size = "2M";
          type = "EF02"; # GRUB BIOS boot on GPT
        };
        root = {
          size = "100%";
          content = {
            type = "filesystem";
            format = "ext4";
            mountpoint = "/";
          };
        };
      };
    };
  };
}
