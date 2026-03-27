from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppUser


class UserRepository:
    def list(self, db: Session) -> list[AppUser]:
        return list(db.scalars(select(AppUser).order_by(AppUser.id.desc())))

    def get(self, db: Session, user_id: int) -> AppUser | None:
        return db.get(AppUser, user_id)

    def create(self, db: Session, user: AppUser) -> AppUser:
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def update(self, db: Session, user: AppUser, values: dict) -> AppUser:
        for key, value in values.items():
            setattr(user, key, value)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
