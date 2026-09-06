import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.registration_invite_service import create_registration_invite


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a one-time registration invite code.",
    )
    parser.add_argument(
        "--valid-hours",
        type=int,
        default=168,
        help="Invite validity in hours (default: 168).",
    )
    args = parser.parse_args()
    if args.valid_hours <= 0:
        parser.error("--valid-hours must be positive")

    with SessionLocal() as db:
        created = create_registration_invite(
            db,
            valid_for=timedelta(hours=args.valid_hours),
        )

    print("registration invite created")
    print(f"code: {created.code}")
    print(f"expires_at: {created.invite.expires_at.isoformat()}")


if __name__ == "__main__":
    main()
