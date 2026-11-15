"""Run the core and plugin test suites in separate Python processes."""

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    suites = [Path("tests")]
    suites.extend(
        directory.relative_to(ROOT)
        for directory in sorted((ROOT / "plugins").glob("*/tests"))
        if directory.is_dir()
    )
    failed = []
    for suite in suites:
        print(f"\nRunning {suite}", flush=True)
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(suite)],
            cwd=ROOT,
        )
        if result.returncode:
            failed.append(str(suite))

    if failed:
        print(f"\nFailed suites: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
