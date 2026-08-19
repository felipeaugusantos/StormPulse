"""Run a single ingestion cycle synchronously (no broker).

Usable for local development, debugging and CI validation:
    python -m workers.run_once
"""

from __future__ import annotations

import json

from workers.db import session_scope
from workers.pipeline_service import run_ingestion_cycle


def main() -> None:
    with session_scope() as session:
        summary = run_ingestion_cycle(session)
    print(
        json.dumps(
            {
                "frames": summary.frames,
                "cells": summary.cells,
                "risks": summary.risks,
                "alerts": summary.alerts,
            }
        )
    )


if __name__ == "__main__":
    main()
