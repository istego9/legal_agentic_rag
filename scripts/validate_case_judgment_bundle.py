#!/usr/bin/env python3
"""Validate mirrored case-judgment bundle schemas and fixtures."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SRC = ROOT / "apps" / "api" / "src"
if str(API_SRC) not in sys.path:
    sys.path.insert(0, str(API_SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.case_judgment_bundle_validation import (  # noqa: E402
    validate_case_judgment_bundle_mirror,
)


def main() -> int:
    errors = validate_case_judgment_bundle_mirror()
    if errors:
        print("case_judgment_bundle validation failed:")
        for item in errors:
            print(f"- {item}")
        return 1
    print("case_judgment_bundle validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

