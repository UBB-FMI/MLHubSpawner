#!/bin/bash

set -eu

username="${PAM_USER:-}"

if [ -z "$username" ]; then
    exit 0
fi

if [ "$username" = "root" ]; then
    exit 0
fi

passwd_entry="$(getent passwd "$username" || true)"
if [ -z "$passwd_entry" ]; then
    echo "$(date) - User $username not found in NSS" >> /bigdata/userCreate.log
    exit 0
fi

home_dir="$(printf '%s\n' "$passwd_entry" | cut -d: -f6)"

if [ -z "$home_dir" ] || [ "$home_dir" = "/" ]; then
    echo "$(date) - Invalid homeDirectory for $username: '$home_dir'" >> /bigdata/userCreate.log
    exit 0
fi

if [ ! -d "$home_dir" ]; then
    mkdir -p "$home_dir"

    if [ -d /etc/skel ]; then
        cp -a /etc/skel/. "$home_dir"/ 2>/dev/null || true
    fi

    uid="$(id -u "$username")"
    gid="$(id -g "$username")"

    chown -R "$uid:$gid" "$home_dir"
    chmod 700 "$home_dir"

    if [ -d "$home_dir/.ssh" ]; then
        chmod 700 "$home_dir/.ssh"
        chown "$uid:$gid" "$home_dir/.ssh"
    fi

    if [ -f "$home_dir/.ssh/authorized_keys" ]; then
        chmod 600 "$home_dir/.ssh/authorized_keys"
        chown "$uid:$gid" "$home_dir/.ssh/authorized_keys"
    fi

    echo "$(date) - Created home $home_dir for $username" >> /bigdata/userCreate.log
fi

exit 0
