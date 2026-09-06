import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.storage_deletion_service import (
    inspect_storage_deletion_retry,
    retry_storage_deletion_now,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect one exact failed storage deletion and optionally "
            "schedule its retry now."
        ),
    )
    parser.add_argument("storage_key", help="Exact storage key to inspect.")
    parser.add_argument(
        "--retry",
        action="store_true",
        help="Move a failed or abandoned backoff task to database now.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.retry:
            result = retry_storage_deletion_now(db, args.storage_key)
            if result.status == "scheduled":
                db.commit()
        else:
            result = inspect_storage_deletion_retry(db, args.storage_key)

    payload = result.as_dict()
    payload["action"] = (
        "schedule_retry" if result.status == "scheduled" else "none"
    )
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.retryable or result.status == "scheduled" else 1


if __name__ == "__main__":
    raise SystemExit(main())
