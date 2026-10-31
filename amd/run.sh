#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HIPVS_ROOT="${HIPVS_ROOT:-/opt/hipvs}"
ROCM_ROOT="${ROCM_ROOT:-/opt/rocm}"
BRIDGE="${CUVS_BRIDGE_LIB:-${ROOT}/tools/hipvs_bridge/libseekdb_cuvs_bridge.so}"
usage() {
  cat <<'HELP'
Usage: bash amd/run.sh [check|build|smoke|bench|help] [args...]
  check: Validate Linux AMD/ROCm/hipVS prerequisites.
  build: Build bridge and GPU-enabled seekdb observer.
  smoke: Forward args to the GPU smoke test runner.
  bench: Run reproducible CPU-vs-GPU build-time benchmark.
HELP
}
check() {
  local rc=0
  [[ "$(uname -s)" == Linux ]] || { echo "Linux required" >&2; rc=1; }
  case "$(uname -m)" in x86_64|amd64) ;; *) echo "x86_64 required" >&2; rc=1 ;; esac
  [[ -x "$ROCM_ROOT/bin/hipcc" ]] || { echo "Missing hipcc" >&2; rc=1; }
  [[ -f "$HIPVS_ROOT/include/cuvs/core/c_api.h" ]] || { echo "Missing hipVS headers" >&2; rc=1; }
  [[ -f "$HIPVS_ROOT/lib/libcuvs_c.so" ]] || { echo "Missing libcuvs_c.so" >&2; rc=1; }
  [[ -e /dev/kfd ]] || { echo "No ROCm GPU access (/dev/kfd missing)" >&2; rc=1; }
  if command -v rocminfo >/dev/null 2>&1; then
    rocminfo >/dev/null || { echo "rocminfo failed" >&2; rc=1; }
  else
    echo "WARN: rocminfo command unavailable" >&2
  fi
  if (( rc == 0 )); then
    echo "Preflight PASS (acceleration still requires GPU measurement)"
  else
    echo "Preflight FAIL" >&2
  fi
  return "$rc"
}
case "${1:-help}" in
  check) check ;;
  build)
    check
    mkdir -p "$(dirname "$BRIDGE")"
    "$ROOT/tools/hipvs_bridge/build.sh" "$BRIDGE"
    [[ -s "$BRIDGE" ]] || { echo "No bridge output" >&2; exit 1; }
    cd "$ROOT"
    ./build.sh release -DOB_BUILD_CUVS=ON -DOB_BUILD_CUVS_TRACE=ON \
       "-DCUVS_BRIDGE_LIB=$BRIDGE" --make -j"${JOBS:-$(nproc)}"
    ;;
  smoke)
    shift
    exec "$ROOT/docs/gpu-vector-index-hipvs-cuvs/validation/run_gpu_smoke.sh" "$@"
    ;;
  bench)
    shift
    exec python3 "$ROOT/tools/hipvs_bridge/benchmark_hnsw.py" "$@"
    ;;
  help|-h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
