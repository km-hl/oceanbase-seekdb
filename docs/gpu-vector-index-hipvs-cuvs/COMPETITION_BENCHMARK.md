# AMD hipVS HNSW competition: build and benchmark

> Branch: `amd`. This is a port of OceanBase/seekdb PR
> [#1314](https://github.com/oceanbase/seekdb/pull/1314) and
> [#2228](https://github.com/oceanbase/seekdb/pull/2228) (Apache 2.0).
> **The current fork is not independently compiled or tested on AMD GPUs.**
> Do not use upstream benchmarks as this fork's measurements.

## 1. Hardware and software prerequisites

- Linux x86-64 with a ROCm-supported AMD GPU and functioning `rocminfo`.
- Matching ROCm / hipVS C API installations (upstream used ROCm 7.2.4
  and a gfx1100 GPU; other versions/devices require verification).
- Seekdb source dependencies and CMake toolchain; a MySQL-compatible
  `mysql` CLI and Python 3 + NumPy for the benchmark.
- A GPU device accessible to the seekdb observer, including
  `/dev/kfd` and the appropriate `/dev/dri/renderD*`.

A generic VPS or a host without Radeon/ROCm cannot validate acceleration;
the library may fall back to exact CPU scan.

## 2. Build bridge and observer

From the repository root, with `HIPVS_ROOT` and `ROCM_ROOT` pointing
at an installed hipVS and ROCm:

```bash
export HIPVS_ROOT=/opt/hipvs
export ROCM_ROOT=/opt/rocm
export LD_LIBRARY_PATH=/opt/hipvs/lib:/opt/rocm/lib:$LD_LIBRARY_PATH
tools/hipvs_bridge/build.sh /tmp/libseekdb_cuvs_bridge.so

./build.sh release \
  -DOB_BUILD_CUVS=ON \
  -DOB_BUILD_CUVS_TRACE=OFF \
  -DCUVS_BRIDGE_LIB=/tmp/libseekdb_cuvs_bridge.so \
  --make -j"$(nproc)"
```

Use `OB_BUILD_CUVS=OFF` for a normal CPU-only build. The GPU backend
is per-index opt-in, not automatic or globally enabled.

After building, confirm the observer's dynamic libraries resolve:

```bash
ldd /path/to/seekdb | grep -Ei 'cuvs|hip|not found'
rocminfo
```

## 3. Required SQL scenario (load first, create index second)

```sql
CREATE DATABASE IF NOT EXISTS hipvs_bench;
USE hipvs_bench;
CREATE TABLE demo (id BIGINT PRIMARY KEY, v VECTOR(4));
INSERT INTO demo VALUES
  (1, '[0.0,0.0,0.0,0.0]'),
  (2, '[1.0,1.0,1.0,1.0]'),
  (3, '[2.0,2.0,2.0,2.0]');

CREATE VECTOR INDEX demo_idx ON demo(v)
  WITH (distance=l2,type=hnsw,lib=cuvs,m=16,ef_construction=200,ef_search=64);

SELECT id FROM demo ORDER BY l2_distance(v,'[0,0,0,0]')
  APPROXIMATE LIMIT 2;
```

The implementation buffers the dataset and builds a CAGRA GPU graph
lazily on the first approximate query. For small datasets it may use
an exact CPU path. **The three-row demo is a correctness example, not
a GPU acceleration benchmark.**

## 4. Fair CPU-versus-GPU reproducible benchmark

```bash
python3 -m pip install numpy

# Start the same seekdb observer binary built with OB_BUILD_CUVS=ON.
# Do not pass a password in the CLI: use MYSQL_PWD or ~/.my.cnf.
python3 tools/hipvs_bridge/benchmark_hnsw.py \
  --host 127.0.0.1 --port 2881 \
  --rows 10000 --dim 128 --k 10 --probes 5 --runs 3 \
  --output hipvs-10k.json

# Repeat with 50000 and 100000 rows if memory permits.
```

The script creates fresh tables for each run, inserts *identical vectors*
into both backends before starting the timer, then runs:

1. `CREATE VECTOR INDEX ... WITH (lib=vsag)` (CPU baseline).
2. `CREATE VECTOR INDEX ... WITH (lib=cuvs)` (GPU opt-in).

For each trial, report **DDL + first approximate query** (lazy CAGRA
construction must be included), DDL-only time, first-query time,
Recall@K against exact NumPy L2 top-K, and median speedup over
three trials. The script alternates CPU/GPU order, outputs JSON,
and intentionally sets `gpu_execution_verified=false` until GPU
logs and telemetry are checked externally.

## 5. Verify genuine GPU execution and correctness

- In observer logs, look for `[OBVSAG][cuVS] built CAGRA` during a
  large GPU-backed test. Without this, fast queries may be CPU scans.
- During the first approximate query, monitor GPU memory/activity
  with `amd-smi` or a compatible ROCm tool.
- Confirm the observer and bridge load `libcuvs` / `libamdhip64`,
  with no `not found` dependencies.
- Run the existing
  `docs/gpu-vector-index-hipvs-cuvs/validation/run_gpu_smoke.sh`
  with its `--observer`, `--bridge`, `--base-dir`, `--port`,
  `--render`, and `--evidence` options.
- Run the CPU-safe mysqltest
  `vector_index_cuvs_ddl` and test index recreation/restart,
  deleted rows, and both `lib=vsag` and `lib=cuvs` paths.

Limitations: L2 float vectors only for `lib=cuvs`; pre-filter plans
are unsupported on GPU-only indexes, and GPU memory/runtime failures
trigger exact CPU fallback. Do not treat fallback timings as GPU speedup.
The snapshot persists flat vectors; the device graph is lazily rebuilt.
