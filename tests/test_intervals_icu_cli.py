import subprocess
import sys
import unittest
from pathlib import Path


CLI_PATH = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "intervals-icu"
    / "scripts"
    / "intervals_icu_cli.py"
)


class CliSurfaceTests(unittest.TestCase):
    def test_mcp_covered_commands_are_not_advertised_by_cli(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(CLI_PATH), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        commands_line = next(
            line.strip()
            for line in result.stdout.splitlines()
            if line.lstrip().startswith("{")
        )
        advertised = set(commands_line.strip("{}").split(","))
        self.assertTrue(
            {
                "activities",
                "activity",
                "streams",
                "search",
                "wellness",
                "events",
                "sick-set",
                "wellness-update",
            }.isdisjoint(advertised)
        )
        self.assertIn("save-activity", advertised)


if __name__ == "__main__":
    unittest.main()
