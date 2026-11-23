#!/bin/bash
# Usage: ab.sh pre|retry
exec > /tmp/ab-$1.out 2>&1
cd /mnt/e/ManyMesh || exit 1
if [ "$1" = pre ]; then
    B=/root/mmgeo-preretry
else
    B=/root/mm-main-build/tools/mmgeo/mmgeo
fi
for mesh in third_party/meshoptimizer/demo/pirate.obj third_party/models/lucy/lucy.obj \
            assets/models/monkey/monkey.obj assets/models/torus/torus.obj \
            assets/models/sphere/sphere.obj; do
    name=$(basename "$mesh" .obj)
    for ratio in 0.55 0.30; do
        out=/tmp/ab-$1-$name-$ratio
        start=$(date +%s)
        "$B" "$mesh" --mode dag --dag-group 8 --target-ratio "$ratio" \
                --out "$out" > "$out.log" 2>&1
        elapsed=$(( $(date +%s) - start ))
        printf "%s %s %s | %ss | " "$1" "$name" "$ratio" "$elapsed"
        grep -E "^  DAG:" "$out.log" | sed -E "s/^ +//" | tr "\n" "|"
        grep -E "drawn:|worst selected|selected topology" "$out.log" | sed -E "s/^ +//" | tr "\n" "|"
        echo
    done
done
