#!/usr/bin/python3
from inotify.adapters import Inotify
from inotify.calls import InotifyError
from inotify.constants import IN_CREATE, IN_DELETE, IN_DELETE_SELF
from yaml import safe_load, dump
from time import sleep
from json import loads
from re import sub, search
from subprocess import check_output, run, CalledProcessError
from pathlib import Path
from os import chown, geteuid
from sys import stderr
from pwd import getpwnam
from grp import getgrnam

if geteuid() != 0:
    exit("You need to have root privileges to run this script.\nPlease try again, this time using 'sudo'. Exiting.")

CONFIG = {
    'devices': [],
    'mount_path_root': "/share/external",
    'mount_path_owner': "root",
    'mount_path_group': "root",
    'mount_path_perms': 0o755
}
CONFIG_FILE = Path('/etc/autodisk/autodisk.conf')
if not CONFIG_FILE.exists():
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(str(CONFIG_FILE), 'w', encoding='utf8') as configfile:
        dump(CONFIG, configfile, default_flow_style=False, allow_unicode=True)
    print('Configuration file ' + str(CONFIG_FILE) + ' not found, created.', file=stderr)
    exit()


conf = safe_load(open(CONFIG_FILE))
conf_has_errors = False
for key in CONFIG:
    if key not in conf:
        print('Configuration file {} has no key {}, using default value: {}'.format(CONFIG_FILE, key, CONFIG[key]),
              file=stderr)
    elif not isinstance(conf[key], type(CONFIG[key])):
        print('{} wants values of type {} but got {}'.format(key, type(CONFIG[key]), type(conf[key])), file=stderr)
        conf_has_errors = True
if conf_has_errors:
    exit(1)
CONFIG = conf

CONFIG['mount_path_uid'] = getpwnam(CONFIG['mount_path_owner']).pw_uid
CONFIG['mount_path_gid'] = getgrnam(CONFIG['mount_path_group']).gr_gid

NAMES = {'umnt_files': {}}
_DISK_PATH_ROOT = '/dev/disk/by-path/'
_MOUNT_PATH_ROOT = Path(CONFIG['mount_path_root'])
_MOUNT_PATH_ROOT.mkdir(mode=0o755, parents=True, exist_ok=True)
_UMOUNT_FILES_FOLDER = Path(str(_MOUNT_PATH_ROOT.resolve()) + "/_UNMOUNT")
_UMOUNT_FILES_FOLDER.mkdir(parents=True, exist_ok=True)
chown(_UMOUNT_FILES_FOLDER.resolve(), uid=CONFIG['mount_path_uid'], gid=CONFIG['mount_path_gid'])

watcher = Inotify()


def sanitize(input_str) -> str:
    # clean names with special characters
    # example: 'Myshiny USB - #me' becomes 'Myshiny_USB_-_me'
    return sub('[^A-Za-z0-9.-_]+', '_', input_str)


def load_disk(block_dev):
    disk_json = loads(check_output("lsblk -Jio KNAME,MODEL,LABEL,PARTLABEL,SIZE " + _DISK_PATH_ROOT + block_dev,
                                   shell=True).decode("utf-8").strip())
    for blk in disk_json["blockdevices"]:
        if not search("(sd[a-z][0-9]*$)", blk['kname']):
            # First check if all volumes are simple devices controlled by
            # SCSI/libATA driver (eg: sda, sdb4, sdh5, sdz, etc) and not RAID, lvm, etc
            # If we find a device that is not controlled by SCSI/libATA driver,
            # we might have found an lvm o RAID volume, we don't care, we skip the disk
            # Chances are if you have one of these volumes you might want to manage them manually
            break
    else:
        for blk in disk_json["blockdevices"]:
            if block_dev not in NAMES:
                NAMES[block_dev] = {}
            if not blk['model'] is None:  # block_dev is the drive itself
                NAMES[block_dev]["name"] = sanitize(blk['model'] + "_" + blk['size'])
            else:
                disk_part = NAMES[block_dev]["part" + search("([0-9]+$)", blk['kname'])[0]] = sanitize(
                    (blk['label'] if not blk['label'] is None
                     else blk['partlabel'] if not blk['partlabel'] is None
                     else blk['kname']) + "_" + blk['size'])
                #              use filesystem label (usually windows' file explorer assigns them)
                # else:        use partition label (used by linux)
                # last resort: device name                

                mnt_dir = Path("{}/{}/{}".format(_MOUNT_PATH_ROOT, NAMES[block_dev]["name"], disk_part))
                mnt_dir.mkdir(mode=CONFIG['mount_path_perms'], parents=True, exist_ok=True)
                # since this program is aimed at short, not permanent,
                # drive mounts we mount drives with `sync` option,
                # this time we don't need the illusion of a light fast drive,
                # neither we care too much about write cycles,
                # we need to be sure to write instantly for fast unmounting
                # and to be protected from unsecure ejections, power losses, etc...
                run("mount -o sync,uid={},gid={} /dev/{} {}".format(
                    CONFIG['mount_path_uid'], CONFIG['mount_path_gid'], blk['kname'], mnt_dir.resolve()), shell=True)
                create_umount_file(block_dev)


def create_umount_file(block_dev):
    # mounting is quite easy and can be automated,
    # unmounting is not the same:
    # - even if we use `sync` option, directly unplugging the drive is not the best option;
    # - using commands to unmount cancels the benefits of this automation script
    # - mapping physical pushbuttons to drive ports would be a good option but
    #       normal computers don't have exposed gpios for buttons, or don't have enough ones
    #       we could have used an I??C expander but again is not easy to physically
    #       access I??C buses in PCs
    # - last option that came into mind is having an `unmount file`:
    #       a file in a separate folder that you delete to trigger drive unmount
    umnt_file = Path(str(_UMOUNT_FILES_FOLDER.resolve()) + "/DELETE_THIS_FILE_TO_UNMOUNT_" + NAMES[block_dev]['name'])
    umnt_file.touch(mode=0o777)
    NAMES['umnt_files'][str(umnt_file.resolve())] = block_dev
    print(NAMES)
    print('Adding watch for unmount file {}'.format(umnt_file.resolve()))
    watcher.add_watch(str(umnt_file.resolve()), mask=IN_DELETE | IN_DELETE_SELF)


def unmount(block_dev) -> bool:
    block_name = NAMES[block_dev]["name"]
    for part_num, part_name in NAMES[block_dev].items():
        if "part" in part_num:
            try:
                print('Unmounting {}/{}/{}'.format(_MOUNT_PATH_ROOT, block_name, part_name))
                # we need to manually kill (sending SIGTERM)
                # all smbd processes that keep mountpoint locked
                # afaik there is no way to avoid this
                #
                # if other programs behave the same way we'll
                # need to write a proper routine to kill them all
                run("lsof -atc smbd {}/{}/{} | xargs -r kill".format(_MOUNT_PATH_ROOT, block_name, part_name),
                    shell=True)
                check_output("umount {}/{}/{}".format(_MOUNT_PATH_ROOT, block_name, part_name), shell=True)\
                    .decode('utf-8').strip()
            except CalledProcessError:
                print('There was an error unmounting {}, skipping...'.format(part_name))
                run('beep -f 800 -l 750 -r 2 -d 750', shell=True)
                break
    else:
        NAMES['umnt_files'].pop(str(Path(str(_UMOUNT_FILES_FOLDER.resolve()) + "/DELETE_THIS_FILE_TO_UNMOUNT_" +
                                         NAMES[block_dev]['name']).resolve()), None)
        run("rm -r {}/{} && beep".format(_MOUNT_PATH_ROOT, block_name), shell=True)
        return True
    return False


for dev in CONFIG['devices']:
    if Path(_DISK_PATH_ROOT + dev).exists():
        load_disk(dev)

print("Devices:")
print(NAMES)
print("Adding watches")

watcher.add_watch(_DISK_PATH_ROOT, mask=IN_CREATE | IN_DELETE)
for (_, type_names, path, filename) in watcher.event_gen(yield_nones=False):
    if filename in CONFIG['devices']:
        if 'IN_CREATE' in type_names:
            print("Inserted " + filename)
            sleep(2)
            load_disk(filename)
            print(NAMES[filename])
        elif 'IN_DELETE' in type_names:
            print("Removed " + filename)
            for key, val in NAMES['umnt_files'].items():
                if val == filename:
                    watcher.remove_watch(key)
                    run('rm {}'.format(key), shell=True)
                    unmount(NAMES['umnt_files'].pop(key, None))
                    break
            NAMES.pop(filename, None)
    elif path in NAMES['umnt_files']:
        if 'IN_DELETE' in type_names or 'IN_DELETE_SELF' in type_names:
            print('Deleted {}, unmounting related filesystems'.format(path))
            # remove from watch list even if it is not being watched anymore
            # not doing so results in "Path already being watched" when drive is remounted,
            # while the program is actually watching the old deleted file and not the new one with same name
            try:
                watcher.remove_watch(path)
            except InotifyError:
                pass
            if not unmount(NAMES['umnt_files'][path]):
                create_umount_file(NAMES['umnt_files'][path])
