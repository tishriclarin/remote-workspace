#!/bin/sh
set -eu
export LC_ALL=C
case "${SSH_ORIGINAL_COMMAND:-}" in
    true) exit 0 ;;
    'uname -sm') exec /usr/bin/uname -sm ;;
    'cat /proc/uptime') exec /usr/bin/cat /proc/uptime ;;
    *) exit 126 ;;
esac
