#!/usr/bin/env python3
"""Offline SQL heuristic analyzer. Never connects to a database."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def mask_sql(source: str) -> str:
    """Blank comments and quoted strings while preserving offsets/newlines."""
    chars = list(source)
    i, n = 0, len(source)

    def blank(start: int, end: int) -> None:
        for j in range(start, min(end, n)):
            if source[j] != "\n":
                chars[j] = " "

    while i < n:
        start = i
        if source.startswith("/*", i):
            close = source.find("*/", i + 2)
            i = n if close == -1 else close + 2
        elif source[i] == "#" or (source.startswith("--", i) and (i + 2 == n or source[i + 2].isspace())):
            close = source.find("\n", i)
            i = n if close == -1 else close
        elif source[i] in ("'", '"'):
            quote = source[i]
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                elif source[i] == quote:
                    if i + 1 < n and source[i + 1] == quote:
                        i += 2
                    else:
                        i += 1
                        break
                else:
                    i += 1
        else:
            i += 1
            continue
        blank(start, i)
    return "".join(chars)


def audit(sql: str) -> list[dict]:
    masked = mask_sql(sql)
    findings = []

    def emit(code: str, severity: str, message: str, at: int, advice: str) -> None:
        findings.append({
            "code": code, "severity": severity,
            "line": sql.count("\n", 0, at) + 1,
            "message": message, "advice": advice,
        })

    boundaries = [0] + [m.end() for m in re.finditer(";", masked)] + [len(masked)]
    for begin, end in zip(boundaries, boundaries[1:]):
        segment = masked[begin:end]
        stripped = segment.lstrip()
        if not stripped.strip(" ;\n\t"):
            continue
        start = begin + len(segment) - len(stripped)
        if re.match(r"(?i)^UPDATE\b", stripped) and re.search(r"(?i)\bSET\b", segment) and not re.search(r"(?i)\bWHERE\b", segment):
            emit("WRITE_WITHOUT_WHERE", "critical", "UPDATE has no WHERE clause", start, "Verify intended scope. Require backup/transaction and explicit approval before executing.")
        if re.match(r"(?i)^DELETE\s+FROM\b", stripped) and not re.search(r"(?i)\bWHERE\b", segment):
            emit("WRITE_WITHOUT_WHERE", "critical", "DELETE has no WHERE clause", start, "Confirm affected rows, backup and rollback plan before executing.")
        for match in re.finditer(r"(?i)\bSELECT\s+(?:DISTINCT\s+)?\*", segment):
            emit("SELECT_STAR", "info", "SELECT * may read unnecessary columns", begin + match.start(), "Select only columns required by the result contract.")
        for match in re.finditer(r"(?i)\bORDER\s+BY\s+RAND\s*\(\s*\)", segment):
            emit("ORDER_BY_RAND", "medium", "ORDER BY RAND() may cause expensive sorting", begin + match.start(), "Consider bounded sampling and verify statistical semantics.")
        for match in re.finditer(r"(?i)\bOFFSET\s+(\d+)\b", segment):
            if int(match.group(1)) >= 1000:
                emit("DEEP_OFFSET", "medium", "Large OFFSET can make pagination expensive", begin + match.start(), "Compare stable keyset pagination.")
        for match in re.finditer(r"(?i)\bLIMIT\s+(\d+)\s*,\s*\d+", segment):
            if int(match.group(1)) >= 1000:
                emit("DEEP_OFFSET", "medium", "Large LIMIT offset can make pagination expensive", begin + match.start(), "Compare keyset pagination with a unique tie-breaker.")
        for match in re.finditer(r"(?i)\b(?:LOWER|UPPER|DATE|YEAR)\s*\(\s*[\w.]+\s*\)\s*(?:=|<|>)", segment):
            emit("FUNCTION_ON_FILTER", "medium", "A function-wrapped column may hinder index usage", begin + match.start(), "Verify semantics and plan before considering a range/filter rewrite.")

    # Leading wildcard check: match simple literal forms; not a SQL grammar parser.
    # Reuse the original SQL here because masked strings cannot expose the %.
    without_comments = list(sql)
    for match in re.finditer(r"(?s)/\*.*?\*/|--[^\n]*|#[^\n]*", sql):
        for i in range(match.start(), match.end()):
            if sql[i] != "\n":
                without_comments[i] = " "
    for match in re.finditer(r"(?i)\bLIKE\s+'%[^']*'", "".join(without_comments)):
        emit("LEADING_WILDCARD", "medium", "LIKE with leading % can bypass normal B-tree lookup", match.start(), "Consider index/search features only after checking deployed version and semantics.")

    return sorted(findings, key=lambda f: (f["line"], f["code"]))


def markdown(findings: list[dict]) -> str:
    if not findings:
        return "No heuristic patterns detected. This does not prove correctness or optimal performance."
    rows = ["| Line | Severity | Finding | Recommendation |", "|---:|---|---|---|"]
    for f in findings:
        safe = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
        rows.append(f'| {f["line"]} | {safe(f["severity"])} | {safe(f["code"])}: {safe(f["message"])} | {safe(f["advice"])} |')
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline SQL audit; no DB access.")
    parser.add_argument("--sql", type=Path, required=True, help="UTF-8 SQL input file")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    findings = audit(args.sql.read_text(encoding="utf-8"))
    print(json.dumps(findings, ensure_ascii=False, indent=2) if args.format == "json" else markdown(findings))


if __name__ == "__main__":
    main()
