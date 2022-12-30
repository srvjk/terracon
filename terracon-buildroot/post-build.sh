#!/bin/sh

set -u
set -e

# Add a console on tty1
if [ -e ${TARGET_DIR}/etc/inittab ]; then
    grep -qE '^tty1::' ${TARGET_DIR}/etc/inittab || \
	sed -i '/GENERIC_SERIAL/a\
tty1::respawn:/sbin/getty -L  tty1 0 vt100 # HDMI console' ${TARGET_DIR}/etc/inittab
fi

cp ~/projects/buildroot/package/busybox/S10mdev ${TARGET_DIR}/etc/init.d/S10mdev
chmod 755 ${TARGET_DIR}/etc/init.d/S10mdev
cp ~/projects/buildroot/package/busybox/mdev.conf ${TARGET_DIR}/etc/mdev.conf

cp ~/projects/terracon/terracon-buildroot/interfaces ${TARGET_DIR}/etc/network/interfaces
cp ~/projects/terracon/terracon-buildroot/wpa_supplicant.conf ${TARGET_DIR}/etc/wpa_supplicant.conf
cp ~/projects/terracon/terracon-buildroot/sshd_config ${TARGET_DIR}/etc/ssh/sshd_config

cp ~/projects/terracon/terracon/terracon.py ${TARGET_DIR}/opt/terracon.py

