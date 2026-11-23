#!/bin/bash
exec > /tmp/reach3.out 2>&1
cd /mnt/e/ManyMesh || exit 1
B=/root/mm-main-build/tools/mmgeo/mmgeo
for mesh in third_party/meshoptimizer/demo/pirate.obj third_party/models/lucy/lucy.obj \
            assets/models/monkey/monkey.obj assets/models/torus/torus.obj \
            assets/models/sphere/sphere.obj; do
    name=$(basename "$mesh" .obj)
    for ratio in 0.55 0.30; do
        out=/tmp/fx-$name-$ratio
        timeout 900 "$B" "$mesh" --mode dag --dag-group 8 --target-ratio "$ratio" \
                --out "$out" > "$out.log" 2>&1
        printf "%s %.2f | " "$name" "$ratio"
        grep -E "DAG built|drawn:|worst selected" "$out.log" | sed -E "s/^ +//" | tr "\n" "|"
        echo
    done
done
