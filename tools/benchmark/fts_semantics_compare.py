#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare FTS tokenization and indexed search results across two seekdb builds.

Requires the mysql CLI. The index checks assume the *same deterministic*
fts_large_bench dataset has been loaded on both servers by
tools/benchmark/fts_large_bench.sh.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from typing import Any


TOKEN_CASES = [
    ("space_case_and_digits", "SELECT tokenize('THE quick Brown fox_123 and DATABASE', 'space');"),
    ("space_unicode", "SELECT tokenize('The Thé thè 北京 OceanBase', 'space');"),
    ("space_repeated", "SELECT tokenize('database DATABASE database www the', 'space');"),
    ("beng_case", "SELECT tokenize('The QUICK brown Fox jumps over the lazy dog', 'beng');"),
    ("beng_unicode", "SELECT tokenize('Résumé CAFÉ database Engine TEST123', 'beng');"),
    ("ik_mixed", "SELECT tokenize('OceanBase 全文索引分词器 Database 搜索引擎', 'ik');"),
    ("ik_ascii", "SELECT tokenize('Database DATABASE database and quick', 'ik');"),
]

INDEX_CASES = [
    ("row_count", "SELECT COUNT(*) FROM fts_large_bench.docs;"),
    ("cn_match", "SELECT COUNT(*) FROM fts_large_bench.docs WHERE MATCH(title, content) AGAINST('全文索引 分词器');"),
    ("beng_match", "SELECT COUNT(*) FROM fts_large_bench.docs WHERE MATCH(title_en, content_en) AGAINST('database performance audit');"),
    ("mixed_match", "SELECT COUNT(*) FROM fts_large_bench.docs WHERE MATCH(title, content) AGAINST('OceanBase 稳定 database');"),
    ("limited_match", "SELECT COUNT(*) FROM (SELECT id FROM fts_large_bench.docs WHERE MATCH(content) AGAINST('倒排索引 tokenizer') LIMIT 20) t;"),
]


def mysql_query(command: str, sql: str) -> str:
    args = shlex.split(command)
    if not args:
        raise ValueError("empty mysql command")
    args += [
        "--batch", "--raw", "--silent", "--skip-column-names",
        "--default-character-set=utf8mb4", "-e",
        "SET NAMES utf8mb4; SET ob_query_timeout = 100000000000; " + sql,
    ]
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        # Never echo the mysql command: it may contain a password.
        raise RuntimeError(
            "mysql exited with status " + str(result.returncode)
            + ": " + result.stderr.strip()[-1200:]
        )
    return result.stdout.rstrip("\n")


def normalize_tokens(output: str) -> Any:
    """Token arrays are sets/multisets: their hash-map iteration order can vary."""
    rows = output.splitlines()
    canonical = []
    for row in rows:
        try:
            value = json.loads(row)
        except json.JSONDecodeError:
            canonical.append(("raw", row))
        else:
            if isinstance(value, list):
                canonical.append((
                    "json-array",
                    tuple(sorted(json.dumps(item, sort_keys=True, ensure_ascii=False)
                                 for item in value)),
                ))
            else:
                canonical.append((
                    "json", json.dumps(value, sort_keys=True, ensure_ascii=False)
                ))
    return tuple(canonical)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-mysql", required=True,
                        help="mysql command for the baseline seekdb server")
    parser.add_argument("--after-mysql", required=True,
                        help="mysql command for the optimized seekdb server")
    parser.add_argument("--tokenize-only", action="store_true",
                        help="do not require pre-loaded fts_large_bench indexes")
    args = parser.parse_args()

    cases = [(name, sql, True) for name, sql in TOKEN_CASES]
    if not args.tokenize_only:
        cases.extend((name, sql, False) for name, sql in INDEX_CASES)

    failures = 0
    for name, sql, is_token in cases:
        try:
            before = mysql_query(args.before_mysql, sql)
            after = mysql_query(args.after_mysql, sql)
            a = normalize_tokens(before) if is_token else before
            b = normalize_tokens(after) if is_token else after
        except (RuntimeError, ValueError) as exc:
            print(f"ERROR {name}: {exc}", file=sys.stderr)
            return 2
        if a == b:
            print(f"PASS {name}")
        else:
            failures += 1
            print(f"FAIL {name}")
            print(f"  before: {str(a)[:600]}")
            print(f"  after:  {str(b)[:600]}")

    total = len(cases)
    print(f"Result: {total - failures}/{total} semantic checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
