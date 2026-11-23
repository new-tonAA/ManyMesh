#!/bin/bash
exec > /tmp/reach2.out 2>&1
cd /mnt/e/ManyMesh || exit 1
for mesh in third_party/meshoptimizer/demo/pirate.obj third_party/models/lucy/lucy.obj \
            assets/models/monkey/monkey.obj assets/models/torus/torus.obj \
            assets/models/sphere/sphere.obj; do
    name=$(basename "$mesh" .obj)
    for ratio in 0.55 0.30; do
        for tag in fixed prefix; do
            if [ "$tag" = fixed ]; then
                b=/root/mm-main-build/tools/mmgeo/mmgeo
            else
                b=/root/manymesh-composite-build/tools/mmgeo/mmgeo
            fi
            out=/tmp/reach-$name-$ratio-$tag
            timeout 600 "$b" "$mesh" --mode dag --dag-group 8 --target-ratio "$ratio" \
                    --out "$out" > "$out.log" 2>&1
            printf "%s %.2f %-6s | " "$name" "$ratio" "$tag"
            grep -E "DAG built|drawn:|worst selected" "$out.log" | sed -E "s/^ +//" | tr "\n" "|"
            echo
        done
    done
done
