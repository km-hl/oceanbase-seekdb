# seekdb SQL Sentinel

A ModelScope Agent Skill for reviewing SQL safety, likely query-performance issues, and realistic EXPLAIN/index validation steps for OceanBase seekdb/MySQL-compatible environments.

**No third-party Python dependencies. No database connection. No SQL execution.**

## What is included

- SKILL.md — instructions for an AI agent, versioned YAML metadata
- scripts/sql_check.py — offline SQL smell scanner (Markdown or JSON)
- tests/test_sql_check.py — standard library tests
- examples/demo.sql — reproducible example SQL
- scripts/package_skill.py — ModelScope ZIP packaging and metadata validation

## Run

Start in the folder containing SKILL.md:

~~~bash
python scripts/sql_check.py --sql examples/demo.sql --format markdown
python scripts/sql_check.py --sql examples/demo.sql --format json
python -m unittest discover -s tests -v
python scripts/package_skill.py
~~~

Expected archive: dist/seekdb-sql-sentinel.zip. The ZIP has a single SKILL.md at its root. Everything is read-only except packaging the local zip. No pip install required.

## Publish and submit to the OceanBase challenge

1. Open the OceanBase contest “魔搭 Skill 发布” submission modal and click **获取验证行**. Copy the actual full line. Do not generate a new one unless needed.
2. Append that exact line as the **last line** of SKILL.md. Do not wrap it in a quote/code block; do not use a fabricated example. Commit the updated file to the independent ModelScope GitHub branch if you want the source to reflect the published artifact.
3. Put the line alone into a local UTF-8 file named verification.txt (keep this private and outside the skill folder). Verify package metadata and that the last line matches:

   python scripts/package_skill.py --verification-file /path/to/verification.txt --require-verification

4. Upload the generated ZIP as a **public** Skill through https://modelscope.cn/skills. Suggested Skill slug: seekdb-sql-sentinel. Suggested category: developer-tools. Set the source code URL to the GitHub ModelScope branch.
5. Open the public Skill page and check that its SKILL.md ends in the actual line. Copy the final URL in the form https://modelscope.cn/skills/@owner/seekdb-sql-sentinel (use the real owner). Do not append query parameters or URL fragments.
6. Paste that ModelScope URL into the OceanBase submission dialog while the line is still valid; review the automatic test results. If validation fails, fix the content, repackage, **republish** and retry.

**Publishing to GitHub alone does not satisfy the challenge.** This challenge verifies the public ModelScope Skill and the team-specific verification line. Submission eligibility is tied to the registered seekdb repository, but the URL to submit is the ModelScope Skill page, not GitHub.

## Programmatic publication

ModelScope documents a two-step API (upload a ZIP, create a public Skill). See: https://github.com/modelscope/modelscope-skills/blob/main/skills/ms-hub/references/skills-center.md

Publishing needs a user-authenticated ModelScope session or ModelScope token. Do not commit tokens, account passwords, or private credentials. The upload archive should be <= 5 MB.

## Notes and limitations

The SQL checker is deliberately conservative and does not parse every dialect or handle arbitrary nested query structures. It may miss patterns or issue false positives. No query is ever executed. Always compare a real EXPLAIN plan, results, and a benchmark with representative data before optimizing in production.

Source branch: https://github.com/km-hl/oceanbase-seekdb/tree/ModelScope

License: Apache License 2.0 (see the repository root LICENSE).
