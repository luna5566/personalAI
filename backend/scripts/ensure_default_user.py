import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User


def main() -> None:
    with SessionLocal() as db:
        user = db.get(User, settings.default_user_id)
        if user:
            print(f"default user already exists: {user.id}")
            return
        user = User(
            id=settings.default_user_id,
            email="local@example.com",
            password_hash=hash_password("123456"),
            name="本地用户",
        )
        db.add(user)
        db.commit()
        print(f"default user created: {user.id}")


if __name__ == "__main__":
    main()
