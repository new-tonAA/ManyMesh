#!/usr/bin/env bash
# Build and run CPU-only diagnostics in Linux / WSL without changing Windows policies.
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
build_dir="${repo_root}/out/regroup-linux-clang"
cc=${CC:-$(command -v clang-18 || command -v clang)}
cxx=${CXX:-$(command -v clang++-18 || command -v clang++)}
mkdir -p "${build_dir}"
test_status=0
if [[ "${1:-}" != "--experiments-only" ]]; then
cmake -S "${repo_root}" -B "${build_dir}" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER="${cc}" -DCMAKE_CXX_COMPILER="${cxx}" \
    -DUSE_STATIC_LIBCXX=OFF \
    -DFILAMENT_SKIP_SAMPLES=ON -DFILAMENT_SKIP_SDL2=ON \
    -DFILAMENT_SUPPORTS_VULKAN=OFF -DFILAMENT_SUPPORTS_OPENGL=OFF \
    -DFILAMENT_BUILD_TESTING=ON \
    > "${build_dir}/configure.log" 2>&1
cmake --build "${build_dir}" --target mmgeo test_manymesh test_utils -j 4 \
    > "${build_dir}/build.log" 2>&1
cd "${repo_root}"
"${build_dir}/libs/manymesh/test_manymesh" > "${build_dir}/test_manymesh.log" 2>&1 || test_status=1
"${build_dir}/libs/utils/test_utils" > "${build_dir}/test_utils.log" 2>&1 || test_status=1
fi
cd "${repo_root}"
python3 tools/mmgeo/regroup_diagnostics.py --mmgeo "${build_dir}/tools/mmgeo/mmgeo" \
    --out out/regroup-diagnostics-linux | tee "${build_dir}/experiments.log"
exit "${test_status}"
