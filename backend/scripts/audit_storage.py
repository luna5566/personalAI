import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.storage_audit_service import audit_current_storage


def main() -> int:
    with SessionLocal() as db:
        result = audit_current_storage(db)
    print(
        json.dumps(
            result.as_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
