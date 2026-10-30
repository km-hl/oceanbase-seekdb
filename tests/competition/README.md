# AI_PROMPT partial checkpoint

This checkpoint fixes prompt-object validation and template rendering helpers. It is **not a completed AI_PROMPT competition submission**.

## Verified

The standalone native suite compiles the full real `ob_ai_func_utils.cpp` and links real seekdb libraries:

- Changed helper: 34 cases passed, 0 failed, 0 setup blockers.
- Original helper: 26 passed, 8 failed, 0 setup blockers.
- Regressions cover repeated and structured arguments, nested envelopes, malformed placeholders, integer overflow, byte preservation and allocation failures.

Run inside Linux/WSL after configuring a compatible seekdb build and building its core libraries:

```sh
python tests/competition/run_ai_prompt_renderer_native.py \
  --build-dir /path/to/seekdb/build_release \
  --source-root /path/to/source/under/test
```

The runner records exact commands, source SHA-256 and results in the build directory. It does not replace building/testing the complete server.

## Pending / not claimed as passed

- SQL `AI_PROMPT` JSON Array/Object input gates still reject these arguments.
- SQL TEXT/LONGTEXT type inference and LOB materialization still need implementation.
- `AI_COMPLETE` still has an all-string prompt-argument gate.
- The SQL constructor and rendering suites express the intended eventual contract; they are **not green acceptance tests for this checkpoint**.
- The full successful build in the local preparation workflow was the **unmodified baseline**. The changed helper itself has compiled/linked/passed native tests; a changed-source full-server validation is still pending.
- No official platform score or passing submission is claimed.

## SQL regression execution

Use a fresh isolated test instance. `mysql_port_mode=disabled` allows a Unix socket without exposing a passwordless SQL TCP listener. Set `SEEKDB_TEST_SOCKET` to its `run/sql.sock`, then run:

```sh
python tests/competition/test_ai_prompt_integration.py --first
python tests/competition/test_ai_prompt_integration.py -v
python tests/competition/test_ai_prompt_rendering.py -v
```

The rendering suite uses a loopback-only recording protocol fixture and asserts actual request contents. It does not call a real model or replace the official Mock AI service. SQL tests require PyMySQL; connection/model-registration failures are environment blockers, not semantic regression evidence.
