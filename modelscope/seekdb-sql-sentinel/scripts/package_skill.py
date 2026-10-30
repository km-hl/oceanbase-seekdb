#!/usr/bin/env python3
"""Create a ModelScope Skill archive with SKILL.md at ZIP root."""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
NAME = "seekdb-sql-sentinel"
INCLUDE = ("SKILL.md", "README.md", "scripts/sql_check.py",
           "scripts/package_skill.py", "examples/demo.sql", "tests/test_sql_check.py")


def check_skill(verification_file: Path | None, require_verification: bool) -> None:
    content = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if not content.startswith("---\n") or "\n---\n" not in content[4:]:
        raise ValueError("Missing YAML frontmatter")
    header = content.split("\n---\n", 1)[0]
    if not re.search(r"(?m)^name: seekdb-sql-sentinel$", header):
        raise ValueError("Invalid or missing Skill name")
    if not re.search(r"(?m)^version: \d+\.\d+\.\d+$", header):
        raise ValueError("Missing version")
    if not re.search(r"(?m)^description: ", header):
        raise ValueError("Missing description")
    if require_verification and not verification_file:
        raise ValueError("Pass --verification-file with --require-verification")
    if verification_file:
        line = verification_file.read_text(encoding="utf-8").rstrip("\r\n")
        if not line or "\n" in line or "\r" in line:
            raise ValueError("Verification file must contain exactly one full line")
        if content.rstrip("\r\n").splitlines()[-1] != line:
            raise ValueError("SKILL.md final line does not match the exact team verification line")


def package(verification_file: Path | None = None, require_verification: bool = False) -> Path:
    check_skill(verification_file, require_verification)
    output = ROOT / "dist" / f"{NAME}.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for relative in INCLUDE:
            source = ROOT / relative
            if not source.is_file():
                raise FileNotFoundError(source)
            archive.write(source, arcname=relative)
    if output.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("ModelScope archive exceeds 5 MiB")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification-file", type=Path)
    parser.add_argument("--require-verification", action="store_true")
    arguments = parser.parse_args()
    print("Created:", package(arguments.verification_file, arguments.require_verification))


if __name__ == "__main__":
    main()
