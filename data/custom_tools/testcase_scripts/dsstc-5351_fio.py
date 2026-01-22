#!/usr/bin/env python3
"""
DSSTC-5351 fio hook (RCI Test Case).

Implements the fio commands referenced in the DSSTC-5351 steps.
This script defaults to dry-run; pass --execute to run.
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def build_command(device: str, mode: str, runtime: int, name: str, direct: int) -> list[str]:
    return [
        "fio",
        f"--name={name}",
        f"--rw={mode}",
        f"--runtime={runtime}",
        "--time_based",
        f"--direct={direct}",
        "--group_reporting",
        "--output-format=json",
        f"--filename={device}",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DSSTC-5351 fio hook")
    parser.add_argument("--device", required=True, help="NVMe device path (ex: /dev/nvme0n1)")
    parser.add_argument(
        "--mode",
        default="readwrite",
        choices=("readwrite", "read", "write"),
        help="fio rw mode",
    )
    parser.add_argument("--runtime", type=int, default=30, help="runtime in seconds")
    parser.add_argument("--name", default="dsstc_5351", help="fio job name")
    parser.add_argument("--direct", type=int, default=1, help="fio direct flag")
    parser.add_argument("--execute", action="store_true", help="actually run the fio command")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cmd = build_command(args.device, args.mode, args.runtime, args.name, args.direct)
    print("Command:", " ".join(cmd))
    if not args.execute:
        print("Dry-run only (pass --execute to run).")
        return 0

    try:
        proc = subprocess.run(cmd, check=False, text=True)
    except Exception as exc:
        print(f"Execution failed: {exc}", file=sys.stderr)
        return 1
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
