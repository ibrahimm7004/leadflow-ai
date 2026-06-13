from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from .web_api import run_daily_lead_job


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the daily lead automation once and exit.")
    parser.add_argument("--date", dest="run_date", default="", help="Optional run date override in YYYY-MM-DD format.")
    parser.add_argument(
        "--no-notify",
        dest="notify",
        action="store_false",
        help="Skip notification email for this run.",
    )
    parser.add_argument(
        "--require-new-york-hour",
        dest="required_hour",
        type=int,
        default=None,
        help="If set, only run when current America/New_York hour matches this value.",
    )
    parser.set_defaults(notify=True)
    args = parser.parse_args()

    if args.required_hour is not None:
        current_hour = datetime.now(ZoneInfo("America/New_York")).hour
        if current_hour != args.required_hour:
            print(
                json.dumps(
                    {
                        "skipped": True,
                        "reason": f"Current America/New_York hour {current_hour} does not match required hour {args.required_hour}.",
                    },
                    indent=2,
                )
            )
            return 0

    try:
        result = run_daily_lead_job(args.run_date or None, notify=args.notify)
    except Exception as exc:
        print(f"Daily job failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
