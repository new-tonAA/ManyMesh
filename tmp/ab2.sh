#!/bin/bash
exec > /root/ab2.out 2>&1
mkdir -p /root/ab
cd /mnt/e/ManyMesh || exit 1
for spec in "pre /root/mmgeo-preretry" "retry /root/mm-main-build/tools/mmgeo/mmgeo"; do
    set -- $spec
    tag=$1
    B=$2
    for mesh in third_party/meshoptimizer/demo/pirate.obj third_party/models/lucy/lucy.obj; do
        name=$(basename "$mesh" .obj)
        for ratio in 0.55 0.30; do
            out=/root/ab/$tag-$name-$ratio
            start=$(date +%s)
            "$B" "$mesh" --mode dag --dag-group 8 --target-ratio "$ratio" \
                    --out "$out" > "$out.log" 2>&1
            elapsed=$(( $(date +%s) - start ))
            printf "%s %s %s | wall %ss | " "$tag" "$name" "$ratio" "$elapsed"
            grep -E "DAG built|drawn:|worst selected" "$out.log" | sed -E "s/^ +//" | tr "\n" "|"
            echo
        done
    done
done
