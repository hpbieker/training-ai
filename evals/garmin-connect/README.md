# Garmin skill interpretation evaluations

Four synthetic cases cover high UNBALANCED HRV, incomplete morning sync,
future-day Recovery Time, and Training Effect/Stamina interpretation.
`cases.json` contains scenario data, questions and review requirements. These
are semantic fixtures, not complete MCP response schemas or athlete records.

Use a separate temporary directory for each case containing a copy of the
current Garmin skill, input.json and a prompt. Give models only that case,
never the rubric, previous answers or personal context. Use fresh read-only
sessions with no live access. Record model, effort, input/skill hashes, exact
answers and command transcripts. Review meaning and arithmetic manually;
keyword matches do not establish correctness.

The first run used two repetitions per case on Sol and Luna at medium effort:
[findings](results/2026-10-17.md), [per-answer review](results/2026-10-17.json).
Raw fixtures, prompts and transcripts are archived locally under
`outputs/garmin-skill-eval/2026-10-17/` (Git-ignored). The preparation and runner
scripts are included there for reproducibility; their absolute paths are local.
