#!/usr/bin/env python3
"""Shared per-phase run logger (A+B format).

Every phase script tees its progress to stderr AND a per-phase file
`phaseN_<script>.log` under the run dir `output/<slug>/`, so scan and
literature collection read consistently and a finished run keeps its own
trace next to its artifacts. Format is section headers plus timestamped
lines:

    ========== SCAN ==========
    2026-07-06 14:03:11 [INFO] 600 PMIDs collected, tagging genes
    ...

Lines flush immediately, so a running phase is watchable via `tail -f`.
ponytail: module-global handle -- one run per process, no need for a class.
"""
import datetime
import os
import sys

_FILE = None


def open_log(run_dir, name):
    """Create run_dir and open <run_dir>/<name> for live logging.

    name is the per-phase file, e.g. 'phase1_fetch_genes.log'.
    """
    global _FILE
    run_dir = run_dir or "."
    os.makedirs(run_dir, exist_ok=True)
    _FILE = open(os.path.join(run_dir, name), "w", encoding="utf-8")


def _emit(line):
    print(line, file=sys.stderr)
    if _FILE:
        _FILE.write(line + "\n")
        _FILE.flush()


def section(title):
    """Blank line + `========== TITLE ==========` block header."""
    _emit("")
    _emit(f"========== {title} ==========")


def info(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _emit(f"{ts} [INFO] {msg}")
