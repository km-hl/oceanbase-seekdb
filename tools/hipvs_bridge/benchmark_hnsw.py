#!/usr/bin/env python3
"""Reproducible seekdb lib=vsag vs lib=cuvs build-to-first-query comparison.

Requirements: Python 3, numpy, mysql CLI, a running seekdb observer.
This script does NOT infer that a fast query used a GPU: inspect observer logs
for [OBVSAG][cuVS] built CAGRA, device usage, and linked ROCm libraries.
"""
import argparse
import datetime
import json
import os
import re
import statistics
import subprocess
import time

import numpy as np


def safe_name(value):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,48}", value):
        raise ValueError("unsafe SQL identifier")
    return value


def mysql(sql, args, database=None):
    cmd = [
        "mysql", "--protocol=TCP", "--batch", "--skip-column-names",
        "--connect-timeout=10", "-h", args.host, "-P", str(args.port),
        "-u", args.user,
    ]
    if database:
        cmd += ["-D", database]
    env = os.environ.copy()
    if args.password_env and args.password_env in env:
        env["MYSQL_PWD"] = env[args.password_env]
    result = subprocess.run(
        cmd, input=sql, capture_output=True, text=True,
        env=env, timeout=args.timeout, check=False,
    )
    if result.returncode:
        raise RuntimeError("mysql failed: " + result.stderr[-3000:])
    return result.stdout.strip()


def vector_literal(v):
    return "[" + ",".join(format(float(x), ".8g") for x in v) + "]"


def ground_truth(vectors, probe, k):
    d = np.sum((vectors - probe) ** 2, axis=1)
    top = np.argpartition(d, k - 1)[:k]
    return set(int(i) for i in top)


def load_data(args, db, table, vectors):
    mysql("CREATE TABLE " + table +
          " (id BIGINT PRIMARY KEY, v VECTOR(" + str(args.dim) + "));", args, db)
    for start in range(0, len(vectors), args.batch):
        sql_rows = []
        for j in range(start, min(start + args.batch, len(vectors))):
            sql_rows.append("(" + str(j) + ",'" + vector_literal(vectors[j]) + "')")
        mysql("INSERT INTO " + table + " VALUES " + ",".join(sql_rows) + ";",
              args, db)
    count = int(mysql("SELECT COUNT(*) FROM " + table + ";", args, db))
    if count != len(vectors):
        raise RuntimeError("loaded row count mismatch")


def ann(args, db, table, probe):
    sql = (
        "SELECT id FROM " + table +
        " ORDER BY l2_distance(v,'" + vector_literal(probe) +
        "') APPROXIMATE LIMIT " + str(args.k) + ";"
    )
    out = mysql(sql, args, db)
    ids = [int(x) for x in out.splitlines() if x.strip()]
    if len(ids) != args.k or len(set(ids)) != args.k:
        raise RuntimeError("ANN result cardinality/uniqueness failed: " + repr(ids))
    return ids


def run_once(args, vectors, probes, backend, run_no, truths):
    db = safe_name(args.database)
    table = safe_name("bench_" + backend + "_" + str(run_no))
    mysql("DROP TABLE IF EXISTS " + table + ";", args, db)
    try:
        load_data(args, db, table, vectors)
        ddl = (
            "CREATE VECTOR INDEX idx_bench ON " + table + "(v) "
            "WITH (distance=l2,type=hnsw,lib=" + backend +
            ",m=16,ef_construction=200,ef_search=64);"
        )
        t0 = time.perf_counter()
        mysql(ddl, args, db)
        ddl_sec = time.perf_counter() - t0

        # Important: the GPU CAGRA build is lazy, so the FIRST ANN query
        # belongs to index build time. Never report DDL alone as build speedup.
        t1 = time.perf_counter()
        first_ids = ann(args, db, table, probes[0])
        first_sec = time.perf_counter() - t1
        hits = len(set(first_ids) & truths[0])
        for query, expected in zip(probes[1:], truths[1:]):
            hits += len(set(ann(args, db, table, query)) & expected)
        recall = hits / (len(probes) * args.k)
        return {
            "backend": backend, "run": run_no,
            "ddl_s": round(ddl_sec, 6),
            "first_query_s": round(first_sec, 6),
            "build_to_first_query_s": round(ddl_sec + first_sec, 6),
            "recall_at_k": round(recall, 6),
        }
    finally:
        if not args.keep_tables:
            mysql("DROP TABLE IF EXISTS " + table + ";", args, db)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=2881)
    p.add_argument("--user", default="root")
    p.add_argument("--password-env", default="MYSQL_PWD")
    p.add_argument("--database", default="hipvs_bench")
    p.add_argument("--rows", type=int, default=10000)
    p.add_argument("--dim", type=int, default=128)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--probes", type=int, default=5)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--batch", type=int, default=100)
    p.add_argument("--seed", type=int, default=1314)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--keep-tables", action="store_true")
    p.add_argument("--output", default="hipvs-hnsw-benchmark.json")
    args = p.parse_args()
    if min(args.rows, args.dim, args.k, args.probes, args.runs, args.batch) < 1:
        p.error("rows, dim, k, probes, runs and batch must be positive")
    if args.rows < max(args.k, args.probes):
        p.error("rows must be >= k and probes")

    db = safe_name(args.database)
    rng = np.random.default_rng(args.seed)
    vectors = rng.uniform(-1.0, 1.0, (args.rows, args.dim)).astype("float32")
    probes = vectors[:args.probes].copy()
    truths = [ground_truth(vectors, q, args.k) for q in probes]

    mysql("CREATE DATABASE IF NOT EXISTS " + db + ";", args)
    results = []
    for run in range(args.runs):
        # Alternate execution order across runs to reduce systematic bias.
        order = ["vsag", "cuvs"] if run % 2 == 0 else ["cuvs", "vsag"]
        for backend in order:
            row = run_once(args, vectors, probes, backend, run + 1, truths)
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)

    cpu = statistics.median(x["build_to_first_query_s"]
                            for x in results if x["backend"] == "vsag")
    gpu = statistics.median(x["build_to_first_query_s"]
                            for x in results if x["backend"] == "cuvs")
    report = {
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rows": args.rows, "dimensions": args.dim, "k": args.k,
        "probes": args.probes, "runs": args.runs, "seed": args.seed,
        "index_parameters": "distance=l2,type=hnsw,m=16,ef_construction=200,ef_search=64",
        "results": results,
        "median_cpu_build_to_first_query_s": cpu,
        "median_gpu_build_to_first_query_s": gpu,
        "speedup": round(cpu / gpu, 4) if gpu > 0 else None,
        "gpu_execution_verified": False,
        "gpu_verification_note": "REQUIRED: correlate with [OBVSAG][cuVS] built CAGRA, GPU VRAM usage and dynamic libraries; script cannot confirm GPU execution.",
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Saved:", args.output)
    print("Build-to-first-query speedup: %.3fx (GPU participation NOT verified)" %
          report["speedup"])


if __name__ == "__main__":
    main()
