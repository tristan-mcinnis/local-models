"""The house command manifest: what this daemon lets other apps do.

`design-system/docs/app-commands.md` is the contract. Quick Launch is the
front door: it reads one small JSON file per app from

    ~/Library/Application Support/House/commands/<app-id>.json

and shows every app's commands in one launcher, without knowing any app by
name. This module is that file for local-models, plus the two documents the
contract makes the daemon answer: the status document behind the manifest's
`status` route, and the choices a command that `needs` one is picked from.

Everything here is derived from the same per-model state `GET /v1/models`
reports, so the launcher and the model list can never disagree.

Three things the contract leaves open for the `http` transport, decided here
and documented in the README so a reader never has to guess:

- **Method.** A command is `POST {endpoint}{verb}`; the `status` and
  `choicesFrom` routes are `GET`. The daemon already shaped its routes that
  way, so nothing is bent to fit.
- **The argument.** A command whose `needs` is not null is posted as
  `{"argument": "<value>"}` — the same one-argument shape the socket protocol
  sends after the verb. `/v1/warm` and `/v1/unload` accept it as a synonym for
  `model`, so the existing wire format is untouched and a caller needs to know
  nothing about this daemon's own field names.
- **A dynamic choice list.** The registry changes while the daemon runs (a
  `local-model pull` adds a model), so a list baked into a file written at
  launch would be wrong by lunchtime. The manifest names a route to read
  instead, in one extra field, `choicesFrom`. This is the only field here the
  contract does not define.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path

#: The contract's schema version. Bump only with the contract.
SCHEMA = 1
APP_ID = "models"
APP_NAME = "Local Models"
#: Routes the manifest points a reader at.
STATUS_ROUTE = "/v1/status"
CHOICES_ROUTE = "/v1/choices/model"


def commands_dir() -> Path:
    """Where every house app drops its manifest.

    `$HOUSE_COMMANDS_DIR` overrides it so a test (or a second daemon on a spare
    port) never writes over the manifest of the daemon a person is using.
    """
    override = os.environ.get("HOUSE_COMMANDS_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "House" / "commands"


def manifest_path() -> Path:
    return commands_dir() / f"{APP_ID}.json"


def build_manifest(base_url: str) -> dict:
    """The manifest document. Static: the command set does not change at run
    time, only which models the commands can be pointed at."""
    return {
        "schema": SCHEMA,
        "app": APP_ID,
        "name": APP_NAME,
        "transport": "http",
        "endpoint": base_url,
        "status": STATUS_ROUTE,
        "commands": [
            {
                "id": "model.warm",
                "title": "Warm Model",
                "verb": "/v1/warm",
                "needs": "choice",
                "choicesFrom": CHOICES_ROUTE,
                "unavailableWhen": None,
            },
            {
                "id": "model.unload",
                "title": "Unload Model",
                "verb": "/v1/unload",
                "needs": "choice",
                "choicesFrom": CHOICES_ROUTE,
                # Nothing resident, nothing to free. Unloading a cold model is
                # still a success, per the contract's idempotence rule; this
                # only keeps a useless row out of the launcher.
                "unavailableWhen": "!warm",
            },
        ],
    }


def status_document(states: list[dict]) -> dict:
    """The contract's status document, from the per-model state of
    `GET /v1/models`.

    `ok` is true whenever this is answered at all: the daemon serving is what
    "ok" means here, and a daemon that cannot serve produces no document, which
    the contract already tells a reader to treat as unavailable. A vision
    backend that is down is degradation, not the daemon being down — that is
    what `GET /health` is for, per backend.
    """
    warm_count = sum(1 for state in states if state.get("warm"))
    busy = any(state.get("in_flight") for state in states)
    if busy:
        detail = "Working"
    elif warm_count == 1:
        detail = "1 model warm"
    elif warm_count:
        detail = f"{warm_count} models warm"
    else:
        detail = "Idle"
    return {
        "app": APP_ID,
        "ok": True,
        "busy": busy,
        # Named by the `unavailableWhen` clause on Unload Model.
        "warm": warm_count > 0,
        "detail": detail,
    }


def model_choices(states: list[dict]) -> list[dict]:
    """What a `needs: "choice"` command can be pointed at, right now.

    The registry id is the title: it is the name a person already types at
    `local-model use <id>`, so the launcher and the CLI call a model the same
    thing.
    """
    return [
        {
            "id": state["id"],
            "title": state["id"],
            "detail": "Warm" if state.get("warm") else "Cold",
        }
        for state in states
    ]


def write_manifest(base_url: str, path: Path | None = None) -> Path | None:
    """Publish the manifest. Returns the path written, or None on any failure.

    Losing remote control must never cost the primary function, so this raises
    nothing: an unwritable directory, a read-only disk or a full one is logged
    once and the daemon goes on serving. Written to a temporary file and moved
    into place, so a reader never catches a half-written manifest.
    """
    target = path or manifest_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(build_manifest(base_url), indent=2) + "\n"
        handle, temp_name = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.")
        try:
            with os.fdopen(handle, "w") as stream:
                stream.write(body)
            os.replace(temp_name, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise
        return target
    except Exception as exc:  # noqa: BLE001 - a manifest is never worth a daemon
        print(f"warning: could not publish command manifest: {exc}", file=sys.stderr, flush=True)
        return None
