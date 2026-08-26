"""Validate fixtures (or any zone package / ledger) from the command line.

    python -m backend.validation.cli
    python -m backend.validation.cli path/to/zone.json --ledger path/to/ledger.json

Exit code 0 when every subject is commit-worthy. Warnings never fail the run.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from .validator import validate_ledger, validate_zone_package

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_LEDGER = ROOT / "fixtures" / "ledger_new_game.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rpg-magic validate")
    parser.add_argument("packages", nargs="*", type=pathlib.Path,
                        help="zone packages to validate (default: fixtures/zone_town_01.json)")
    parser.add_argument("--ledger", type=pathlib.Path, default=DEFAULT_LEDGER)
    parser.add_argument("--broken", action="store_true",
                        help="also run the broken fixture library; each file must fail")
    args = parser.parse_args(argv)

    ledger = json.loads(args.ledger.read_text())
    reports = [validate_ledger(ledger)]

    packages = args.packages or [ROOT / "fixtures" / "zone_town_01.json"]
    for path in packages:
        report = validate_zone_package(json.loads(path.read_text()), ledger)
        report.subject = str(path)
        reports.append(report)

    failed = [r for r in reports if not r.ok]
    for report in reports:
        print(report)
        print()

    if args.broken:
        broken_dir = ROOT / "fixtures" / "broken"
        expected = json.loads((broken_dir / "expected.json").read_text())
        print("broken fixture library")
        for filename, spec in sorted(expected.items()):
            report = validate_zone_package(json.loads((broken_dir / filename).read_text()), ledger)
            want = set(spec["expect_error_codes"])
            got = report.error_codes()
            missing = want - got
            status = "caught" if (not report.ok and not missing) else "MISSED"
            if status == "MISSED":
                failed.append(report)
            print(f"  {status:>6}  {filename:<32} {sorted(want)}"
                  + (f"  -- missing {sorted(missing)}" if missing else ""))
        print()

    print("OK" if not failed else f"FAILED ({len(failed)} subject(s))")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
