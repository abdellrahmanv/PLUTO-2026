#!/usr/bin/env python3
"""Terminal runner for Stage 2 Validation Center tests.

The runner calls the active Pluto website API so hardware tests reuse the
single live web-shell owner of the STM32 serial link.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def request_json(base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Pluto Stage 2 validation test through the website API.")
    parser.add_argument("--test", required=True, help="Validation test id, for example bldc-motor-physical.")
    parser.add_argument("--base-url", default=os.environ.get("PLUTO_WEB_URL", "http://127.0.0.1:18091"))
    parser.add_argument("--confirm-physical", action="store_true", help="Confirm physical motion tests are supervised.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON result.")
    args = parser.parse_args()

    try:
        result = request_json(args.base_url, "/api/validation/run", {"test_id": args.test, "confirmed": args.confirm_physical})
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - terminal runner should show exact connection failure
        print(f"TEST_RUNNER_FAILURE: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result.get('name', args.test)}: {result.get('status')}")
        if result.get("failure_classification"):
            print(f"classification: {result['failure_classification']}")
        if result.get("measurements"):
            print("measurements:")
            print(json.dumps(result["measurements"], indent=2))
        if result.get("output"):
            print("logs:")
            print(result["output"])

    status = result.get("status")
    return 0 if status in {"PASS", "WARNING", "HARDWARE NOT DETECTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
