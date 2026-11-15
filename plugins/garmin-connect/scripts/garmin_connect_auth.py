"""Set up a local Garmin Connect session for the MCP plugin."""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path


class GarminLoginError(RuntimeError):
    """A Garmin session could not be established."""


def resolve_token_store() -> str:
    default = Path.home() / ".config" / "training-ai" / "garmin"
    return str(Path(os.environ.get("TRAINING_AI_GARMIN_TOKEN_STORE", default)).expanduser())


def load_credentials(*, interactive: bool) -> tuple[str, str]:
    """Read Garmin login settings from the user's local JSON file."""
    path = Path(os.environ.get("GARMIN_MCP_CONFIG", Path.home() / ".garmin_mcp.json")).expanduser()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if not interactive:
            raise GarminLoginError(
                "Configure Garmin username and password in ~/.garmin_mcp.json "
                "(or GARMIN_MCP_CONFIG)."
            ) from None
        if "GARMIN_MCP_CONFIG" in os.environ:
            raise
        return input("Garmin email: ").strip(), getpass("Garmin password: ")

    if not isinstance(config, dict):
        raise ValueError("Garmin config must contain a JSON object.")
    username = config.get("username")
    password = config.get("password")
    if (
        not isinstance(username, str) or not username.strip()
        or not isinstance(password, str) or not password
    ):
        raise ValueError("Garmin config requires username and password.")
    return username.strip(), password


def login(token_store: str, *, interactive: bool) -> None:
    try:
        from garminconnect import Garmin

        username, password = load_credentials(interactive=interactive)
        garmin = Garmin(
            username,
            password,
            prompt_mfa=(lambda: getpass("Garmin MFA code: ").strip()) if interactive else None,
            return_on_mfa=not interactive,
        )
        # Use the supplied credentials even if another integration has set a token store.
        status, _ = garmin.login("{}")
        if status == "needs_mfa":
            raise GarminLoginError(
                "Garmin requires MFA. Run garmin_connect_auth.py login in a terminal."
            )
        if not garmin.client.di_refresh_token:
            raise GarminLoginError("Garmin did not provide a renewable session.")
        garmin.client.dump(token_store)
    except GarminLoginError:
        raise
    except Exception:
        raise GarminLoginError(
            "Garmin login failed. Check the Garmin config or run "
            "garmin_connect_auth.py login in a terminal."
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("login",))
    parser.parse_args()
    try:
        login(resolve_token_store(), interactive=True)
    except GarminLoginError as error:
        print(error, file=sys.stderr)
        return 1

    print("Garmin session saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
