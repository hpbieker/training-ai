#!/usr/bin/env python3
"""Build local Python MCP plugins for macOS arm64."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.13"


def build(plugin: str) -> None:
    source = ROOT / "plugins" / plugin
    destination = ROOT / "dist" / plugin
    subprocess.run(["uv", "python", "install", "--no-bin", PYTHON_VERSION], check=True)
    python = Path(subprocess.check_output(
        ["uv", "python", "find", "--managed-python", PYTHON_VERSION], text=True,
    ).strip()).resolve(strict=True)
    subprocess.run(
        [str(python), "-I", "-S", "-B", "-c",
         "import platform, sys; "
         "assert sys.platform == 'darwin' and platform.machine() == 'arm64' "
         "and sys.version_info[:2] == (3, 13), 'Expected macOS arm64 and Python 3.13'"],
        check=True,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{plugin}-", dir=destination.parent,
    ) as temporary:
        staging = Path(temporary) / "plugin"
        staging.mkdir()
        directories = [source / name for name in (".codex-plugin", "assets", "skills")]
        if (source / "scripts").is_dir():
            directories.append(source / "scripts")
        for directory in directories:
            shutil.copytree(
                directory, staging / directory.name,
                ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
                symlinks=True,
            )
        for file in (source / ".mcp.json", *sorted(source.glob("*.py"))):
            shutil.copy2(file, staging, follow_symlinks=False)
        environment = staging / ".venv"
        interpreter = environment / "bin" / "python"
        subprocess.run(
            [str(python), "-B", "-m", "venv", "--copies", "--without-pip", str(environment)],
            check=True,
        )
        subprocess.run(
            ["uv", "pip", "sync", "--python", str(interpreter), "--link-mode", "copy",
             "--only-binary", ":all:",
             str(source / "requirements.lock")],
            check=True,
        )
        # Activation and package CLI scripts refer to the build directory.
        for path in interpreter.parent.iterdir():
            if path != interpreter:
                path.unlink()
        if any(path.is_symlink() for path in staging.rglob("*")):
            raise RuntimeError("The Codex plugin package must contain no symbolic links")

        previous = Path(temporary) / "previous"
        if destination.exists():
            destination.rename(previous)
        try:
            staging.rename(destination)
        except OSError:
            if previous.exists():
                previous.rename(destination)
            raise
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    plugins = sorted(lock.parent.name for lock in (ROOT / "plugins").glob("*/requirements.lock"))
    parser.add_argument("plugin", choices=plugins)
    build(parser.parse_args().plugin)
