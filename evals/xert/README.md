# Xert skill evaluations

`cases.json` contains four synthetic scenarios and separate review criteria:
remaining dose after completed training, capacity versus recommended dose,
positive Low recovery time, and multiple planned workouts. Model packages
contain the current skill, scenario input and actual relevant MCP definitions,
but not review criteria. No personal training records or live Xert access are
used.

Run each case in a fresh read-only session on Sol and Luna at medium effort.
Models explain their answer and propose calls; the Xert MCP server is not
connected. Review both interpretation and proposed tool contracts manually.
This tests reasoning and tool selection, not successful live execution.

## Local plugin tests

Use an isolated environment with the plugin's declared dependencies:

```sh
python3.14 -m venv /private/tmp/xert-test-venv
/private/tmp/xert-test-venv/bin/python -m pip install -r plugins/xert/requirements.txt
/private/tmp/xert-test-venv/bin/python -B -m unittest discover -s tests -p 'test_xert*.py'
```

On 17 October 2026, all 155 tests passed using Python 3.14, MCP 1.30.0 and
AnyIO 4.15.1. The two previously failing tests were missing-dependency errors;
no production-code change was needed.

The evaluation package, runner, preparation script, file hashes, dependency
versions and raw model outputs are archived locally under
`outputs/xert-skill-eval/2026-10-17/` (Git-ignored). Do not treat this small
synthetic evaluation as evidence of universal reliability.

Results: [17 October review](results/2026-10-17.md) and
[full per-answer assessments](results/2026-10-17.json).

The [absolute-timestamp follow-up](results/2026-10-17-postfix.md) reran the
multiple-workout case twice per model with the revised MCP contract; all four
answers passed the targeted regression.
