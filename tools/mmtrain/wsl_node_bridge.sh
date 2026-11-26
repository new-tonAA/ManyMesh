#!/bin/sh
# Let WSL Python benchmark scripts call a Windows Node executable safely.
# Set MANYMESH_WINDOWS_NODE when node.exe is not at the D-drive default.
set -eu

windows_node=${MANYMESH_WINDOWS_NODE:-/mnt/d/Nodejs/node.exe}
if [ "$#" -eq 1 ] && [ "$1" = "--version" ]; then
    exec "$windows_node" --version
fi
if [ "$#" -ne 3 ]; then
    echo "expected node SCRIPT INPUT OUTPUT" >&2
    exit 2
fi

script=$(wslpath -w "$1" | tr -d '\r')
source=$(wslpath -w "$2" | tr -d '\r')
target=$(wslpath -w "$3" | tr -d '\r')
exec "$windows_node" "$script" "$source" "$target"
