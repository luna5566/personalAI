import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.storage_audit_service import (
    StorageObjectNotOrphanError,
    enqueue_orphan_deletion,
    inspect_orphan_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify one exact storage key and optionally enqueue its deletion."
        ),
    )
    parser.add_argument("storage_key", help="Exact storage key to verify.")
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Persist a deletion task after the orphan check passes.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        if not args.enqueue:
            inspection = inspect_orphan_status(db, args.storage_key)
            _print_json(
                {
                    **inspection.as_dict(),
                    "action": "none",
                }
            )
            return 0 if inspection.is_orphan else 1

        try:
            receipt = enqueue_orphan_deletion(db, args.storage_key)
        except StorageObjectNotOrphanError:
            _print_json(
                {
                    "status": "not_orphan",
                    "action": "none",
                    "storage_key": args.storage_key,
                }
            )
            return 1

    _print_json({**receipt.as_dict(), "action": "enqueue"})
    return 0


def _print_json(payload: dict[str, object]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
