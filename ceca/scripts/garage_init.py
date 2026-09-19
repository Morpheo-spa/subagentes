#!/usr/bin/env python3
"""Bring the stack's Garage from "just started" to "serving a bucket".

    python scripts/garage_init.py            # reads ./.env
    python scripts/garage_init.py .env.prod

Garage will not serve S3 until a cluster layout is applied, and it has no
built-in bucket or credentials: those are three CLI commands that this script
runs for you through ``docker compose exec``, reading the values from .env so
the result is reproducible. Every step is idempotent: run it again and it
reports what is already there.

The Garage image is a bare binary, so everything goes through ``/garage``
inside the running container; no shell is needed and none is assumed.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REQUIRED = ("GARAGE_ACCESS_KEY", "GARAGE_SECRET_KEY")
KEY_NAME = "estampa-api"
ZONE = "dc1"
CAPACITY = "10G"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def garage(*args: str, check: bool = True) -> str:
    inside = ["/garage", "-c", "/etc/garage.toml", *args]
    command = ["docker", "compose", "exec", "-T", "garage", *inside]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    output = (result.stdout + result.stderr).strip()
    if check and result.returncode != 0:
        print(f"  ! {' '.join(args)} failed:\n{output}", file=sys.stderr)
        sys.exit(result.returncode)
    return output


def node_id() -> str:
    status = garage("status")
    # The status table lists nodes as "<16 hex id>  <hostname> ..."; one node here.
    match = re.search(r"(?m)^\s*([0-9a-f]{16})\b", status)
    if not match:
        print(f"could not find a node id in `garage status`:\n{status}", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def main(argv: list[str]) -> int:
    env = parse_env(Path(argv[1] if len(argv) > 1 else ".env"))
    missing = [key for key in REQUIRED if not env.get(key) or "CHANGE_ME" in env[key]]
    if missing:
        print(f"fill these in .env first (python scripts/make_secrets.py): {', '.join(missing)}")
        return 1
    bucket = env.get("GARAGE_BUCKET", "estampa")

    print("== layout")
    layout = garage("layout", "show")
    if "no nodes" in layout.lower() or "capacity" not in layout.lower():
        node = node_id()
        print(garage("layout", "assign", "-z", ZONE, "-c", CAPACITY, node))
        print(garage("layout", "apply", "--version", "1"))
    else:
        print("  layout already applied")

    print("== bucket")
    buckets = garage("bucket", "list")
    if re.search(rf"\b{re.escape(bucket)}\b", buckets):
        print(f"  bucket {bucket} exists")
    else:
        print(garage("bucket", "create", bucket))

    print("== access key")
    keys = garage("key", "list")
    if env["GARAGE_ACCESS_KEY"] in keys:
        print(f"  key {env['GARAGE_ACCESS_KEY']} already imported")
    else:
        print(
            garage(
                "key",
                "import",
                "--yes",
                "-n",
                KEY_NAME,
                env["GARAGE_ACCESS_KEY"],
                env["GARAGE_SECRET_KEY"],
            )
        )

    print("== permissions")
    print(garage("bucket", "allow", "--read", "--write", "--owner", bucket, "--key", KEY_NAME))
    print()
    print("Done. In Estampa, a tenant S3 backend for this Garage is:")
    print("  endpoint_url      http://garage:3900")
    print(f"  bucket            {bucket}")
    print("  region            garage")
    print("  force_path_style  true")
    print(f"  access key        {env['GARAGE_ACCESS_KEY']}  (secret: GARAGE_SECRET_KEY in .env)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
