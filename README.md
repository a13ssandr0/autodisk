# Autodisk (beta)
Automatically mount a drive if connected to a specific USB or SATA port.

## Contents:
- [Introduction](#introduction)
    - [The story](#the-story)
    - [Implementation](#implementation)
    - [The unmount file](#the-unmount-file)
- [Installation](#installation)
    - [Dependencies](#dependencies)
    - [First run](#first-run)
    - [Adding ports](#adding-ports)
    - [Autostart on boot](#autostart-on-boot)
- [Usage](#usage)
    - [Enabling acoustic notification](#enabling-acoustic-notification)
    - [Disabling acoustic notification](#disabling-acoustic-notification)
- [Troubleshooting](#troubleshooting)
    - [Disk fails to unmount](#disk-fails-to-unmount)
    - [No beep sound](#no-beep-sound)
- [Contributing](#contributing)


## Introduction
### The story
When switching from a commercial NAS to a custom Linux based server, I noticed one thing was missing: commercial NAS automatically mounted usb and eSATA drives and provided them as a network share without even touching web admin interface.

Searching online I saw it was possible to identify a disk by physical bus connection, wether it was SATA, USB or NVMe (and maybe other connections, but I don't have them, so I haven't done any test), so I could select the ports to use without interfering with other devices like my main RAID configuration.

### Implementation
`udev` provides (by default) a rule that symlinks block devices to `/dev/disk/by-path/` (See [this page](https://unix.stackexchange.com/questions/86764/understanding-dev-disk-by-folders) for more info).
- By watching (with inotify) that path, we can detect when a drive is added to the system and where it was connected
- Then we scan its partitions and mount them only if they are standalone partitions and not part of lvm/RAID volumes (if you have such partitions you may want to manage them manually so we won't touch them)
- For each drive a folder with its name is created, and for each partition it will add a subfolder
- After mounting the first partition the progam creates a file in the `_UNMOUNT` folder and monitors it: when deleted, all the partitions of the corresponding drive will be unmounted.

### The unmount file
Mounting a drive is as simple a running the mount command with some basic options, but unmounting is another story:
- even if we use `sync` option, directly unplugging the drive is not the best option;
- using commands to unmount cancels the benefits of this program
- mapping physical buttons to drive ports would be a good option but normal computers don't have exposed gpios for buttons, or don't have enough ones we could have used an I²C expander but again is not easy to physically access I²C buses in PCs
- last option that came into mind is having an `unmount file`: a file in a separate folder that you delete to trigger drive unmount

## Installation
> All commands here are run after switching to `root` account with
> `sudo su -` or `sudo -s`

At the moment the program is provided as a simple script and has no automatic installation method. You can use this command to install it in `/usr/sbin` (remember to run it as root)
```sh
wget -O /usr/sbin/autodisk https://raw.githubusercontent.com/a13ssandr0/autodisk/master/autodisk.py
chmod 755 /usr/sbin/autodisk
```

### Dependencies
To run correctly Autodisk needs the following linux programs:
- `udev` with rule `60-persistent-storage.rules` enabled (should be already present in normal installation, unless you are running a highly customized OS with different rules or even without udev)
- `lsblk`
- `mount`
- `umount`
- `lsof` and `xargs` (only needed in [certain cases](#disk-fails-to-unmount))
- `beep` and kernel module `pcspkr` enabled ([see later](#enabling-acoustic-notification))

It also needs `python3` (version 3.8.10 was used during testing) and the following packages:
- `inotify`
- `PyYAML`

### First run
After installation, run the program manually (as root) to create the configuration file, `/etc/autodisk/autodisk.conf` is automatically generated with default parameters:
```yaml
devices: []
mount_path_owner: root
# the user that owns the mountpoint
mount_path_group: root
# the group that can access the mount point
mount_path_perms: 493
# UNIX permissions for mountpoint (default rwxr-xr-x)
# this is the base10 equivalent of base8 0755
# feel free to use base8 or base10 numbers, just remember octals start with a 0, eg. 0755
mount_path_root: /share/external
# the main folder that will contain the mountpoints
```

### Adding ports
The `devices` key in `autodisk.conf` is a list of devices you want to monitor.

For example on an Asus Maximus VII Gene motherboard we want to automatically mount everything plugged in the front USB 3.0 header and in SATA ports number 5 and 6, devices will be
```yaml
devices:
    - pci-0000:00:14.0-usb-0:1:1.0-scsi-0:0:0:0
    - pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0
    - pci-0000:00:1f.2-ata-5
    - pci-0000:00:1f.2-ata-6
```

To get the corresponding name for each device first of all unplug all devices from the port you want to use and run
```
$ ls -1 /dev/disk/by-path/
pci-0000:00:1f.2-ata-1
pci-0000:00:1f.2-ata-1-part1
pci-0000:00:1f.2-ata-2
pci-0000:00:1f.2-ata-2-part1
pci-0000:00:1f.2-ata-3
pci-0000:00:1f.2-ata-3-part1
pci-0000:00:1f.2-ata-4
pci-0000:00:1f.2-ata-4-part1
pci-0000:04:00.0-nvme-1
pci-0000:04:00.0-nvme-1-part1
pci-0000:04:00.0-nvme-1-part2
```
Take note of the output, plug some devices in the ports you want to monitor and rerun the command
```
$ ls -1 /dev/disk/by-path/
pci-0000:00:14.0-usb-0:1:1.0-scsi-0:0:0:0
pci-0000:00:14.0-usb-0:1:1.0-scsi-0:0:0:0-part1
pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0
pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0-part1
pci-0000:00:1f.2-ata-1
pci-0000:00:1f.2-ata-1-part1
pci-0000:00:1f.2-ata-2
pci-0000:00:1f.2-ata-2-part1
pci-0000:00:1f.2-ata-3
pci-0000:00:1f.2-ata-3-part1
pci-0000:00:1f.2-ata-4
pci-0000:00:1f.2-ata-4-part1
pci-0000:00:1f.2-ata-5
pci-0000:00:1f.2-ata-5-part1
pci-0000:00:1f.2-ata-6
pci-0000:00:1f.2-ata-6-part1
pci-0000:04:00.0-nvme-1
pci-0000:04:00.0-nvme-1-part1
pci-0000:04:00.0-nvme-1-part2
```
As you can see new devices appeared along with their partitions, we will consider only the drives, not the partitions
- pci-0000:00:14.0-usb-0:1:1.0-scsi-0:0:0:0
- pci-0000:00:14.0-usb-0:2:1.0-scsi-0:0:0:0
- pci-0000:00:1f.2-ata-5
- pci-0000:00:1f.2-ata-6

### Autostart on boot (systemd)
To automatically start the program create a new systemd service
```sh
sudo nano /lib/systemd/system/autodisk.service
```
And paste this content
```ini
[Unit]
Description=Autodisk daemon

[Service]
ExecStart=/usr/sbin/autodisk
Environment=PYTHONUNBUFFERED=1

Restart=on-failure
RestartSec=5

KillMode=process
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
```
save the file and exit.
Enable and start the service with
```sh
sudo systemctl enable autodisk.service
sudo systemctl start autodisk.service
```

## Usage
After installation is finished and `autodisk.conf` is ready you can run `/usr/sbin/autodisk` as root (do not use sudo, switch to root account before starting the program, not doing so won't break the program but you won't have acustic notification). However this program is designed to be fully automatic so you should use a [systemd service](#autostart-at-boot-systemd) to start it.

### Enabling acoustic notification
This program uses [`beep`](https://linux.die.net/man/1/beep) to provide acoustic feedback through the internal motherboard speaker, however by default the program is not installed and the required kernel module is blacklisted.

To install it simply use `sudo apt install beep`, then run `sudo modprobe pcspkr`, if everything is successful you should be able to run `beep` as a normal user and hear the default tone.

To keep the module enabled after reboot edit `/etc/modprobe.d/blacklist.conf` with your favouite editor as root (eg. `sudo nano /etc/modprobe.d/blacklist.conf`) then find a line that says
```sh
# ugly and loud noise, getting on everyone's nerves; this should be done by a
# nice pulseaudio bing (Ubuntu: #77010)
blacklist pcspkr
```
and add a `#` at the beginning to comment it.

Check if it worked by rebooting the system and running `beep` after login.

### Disabling acoustic notification
At the moment the program has no option to disable beep (it will be added soon), but if you don't like it you can comment the lines in the source code, or blacklist the module in `/etc/modprobe.d/blacklist.conf`.

## Troubleshooting
### Disk fails to unmount
When testing the program one issue I had to solve was that, if any folder inside the mount point (or even the whole mountpoint) was shared via SMB, the `smbd` daemon kept files and folders locked even when nobody was using them. Since there was no way I could find to disable those locks, I did as others suggested: terminating the processes (that's why we need lsof and xargs) sending them SIGTERM.

If any other program you will be using behaves the same, edit the program to kill it adding another line like this inside the `unmount` function
```python
def unmount(block_dev) -> bool:
    ...
    run("lsof -atc [PROGRAM] {}/{}/{} | xargs -r kill".format(_MOUNT_PATH_ROOT, block_name, part_name), shell=True)
    ...
```
replacing `[PROGRAM]` whith the name of the program you want to kill.

### No beep sound
- Try switching to root user via `sudo su -` and running `beep` without arguments, if it says there are no devices, check if `pcspkr` kernel module is enabled and not blacklisted in any .conf file under `/etc/modprobe/`
- If the command runs successfully but still not hearing anything, check wether the speaker is connected, not damaged and beeps when BIOS POST completes.

## Contributing
This program was written and tested on one platform only, so some features may be missing and some devices may not be supported (eg.: I didn't implement mmcblk support because I don't have MMC cards for testing).

If you manage to make another device working, open an issue describing what you've done, I'll add it to the documentation.

Last but not least, every contribution (even the smallest) is welcome, software is better when done together.

#
#
If you like UniTotem, consider giving me a tip.

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/a13ssandr0)
