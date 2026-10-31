# AMD hipVS / CAGRA V1 optimization and reproducibility report

## Competition contract

- Official frozen base: `634888d9b037153fa143d2c913ba4b25503e1d62`.
- This branch descends from the frozen base through commit
  `2dfdc322d2c30a95b5304717df479dc309e8fe42`.
- Fixed SQL: `CREATE VECTOR INDEX ... WITH (distance=l2,type=hnsw,lib=cuvs,m=16,ef_construction=200,ef_search=64)`.
- Build measurement includes CREATE INDEX **and the first ANN query**, including any deferred construction.
- Evaluation sets: SIFT250K (FP32, 128 dimensions), Hidden250K (FP32, 256 dimensions), both L2.
- A successful candidate must meet Recall minima **and remain within 0.005 of the paired V5 baseline**.
- Each dataset's Top-10 and Top-100 QPS must also meet the baseline-relative 90% gate.
- Query must use the unchanged, organizer-supplied GPU hipVS/CAGRA search implementation.

## Change summary

| Component | V5 baseline | Candidate V1 |
| --- | --- | --- |
| CAGRA initial graph | NN_DESCENT | NN_DESCENT |
| CAGRA graph degree | 128 | 128 |
| CAGRA intermediate degree | 256 | 256 |
| NN-Descent maximum iterations | 100 | 80 |
| Query itopk_size | max(512, topk*4) | unchanged |
| Query search_width | 4 | unchanged |
| GPU query buffers | 3 fresh allocations and frees per request | grow-on-demand per-index buffers |
| GPU search params | allocate/free per request | create once per-index |
| Per-handle concurrency | GPU resources used by caller | serialized by a pthread mutex |

The iteration change may reduce graph construction work, but recall must be
measured on GPU. No claim of faster build or unchanged recall is made without
paired evaluation.

## Reproduction

### GPU/ROCm compiler

Use the **exact** contest-approved, offline build commands (no additional
compiler arguments):

```bash
HIPVS_ROOT=/opt/hipvs ROCM_ROOT=/opt/rocm \
  tools/hipvs_bridge/build.sh /tmp/amd_bridge/libseekdb_cuvs_bridge.so

cmake -S . -B build_release -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DOB_ENABLE_UNITY=ON \
  -DOB_USE_LLD=ON \
  -DOB_BUILD_CUVS=ON \
  -DOB_BUILD_CUVS_TRACE=OFF \
  -DCUVS_BRIDGE_LIB=/tmp/amd_bridge/libseekdb_cuvs_bridge.so
cmake --build build_release --target seekdb
```

### Smoke tests

```bash
# CPU-only interface test, not a GPU/recall benchmark:
bash tools/hipvs_bridge/tests/mock_bridge_smoke.sh

# With a ROCm-capable GPU and the built observer:
docs/gpu-vector-index-hipvs-cuvs/validation/run_gpu_smoke.sh --help
```

For a production measurement, use the **organizer's** identical GPU tests for
base and candidate. Do not use the CPU-only mock as acceleration evidence.
Do not use `dbms_vector.batch_knn` timing for official QPS; official `nq=4096`
is 4096 independent single-query SQLs.

## Performance and correctness evidence

| Measurement | Unmodified V5 in user's last official submission | V1 candidate |
| --- | --- | --- |
| Aggregate build speedup vs V5 | 0.977x | **Not measured** |
| Aggregate query speedup vs V5 | 1.035x | **Not measured** |
| All hard gates | pass | **Not measured** |
| Official score | 4.170/20 | **Not measured** |

The user-provided baseline result is an official one-time score and not a
CPU/GPU microbenchmark. CPU VSAG absolute build time, V1 AMD GPU build time,
Recall@10/100, device-memory peak, and query QPS are **not available** here.
For a complete CPU/GPU comparison report, measure both with identical vectors,
dimension and environment, while separately reporting the official V5-relative
metric, which is what the competition actually scores.

## Revert path

A failed GPU gate or insufficient Recall should not erase the working entry.
The `amd` branch remains at official V5 migration
`2dfdc322d2c30a95b5304717df479dc309e8fe42`.
Submit `amd-opt-v1` by its exact commit hash as a separate trial. Never
claim better performance until the platform confirms gates=pass.
