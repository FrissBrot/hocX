from sqlalchemy.orm import Session

from app.models import AppUser
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, repository: UserRepository | None = None) -> None:
        self.repository = repository or UserRepository()

    def list_users(self, db: Session):
        return self.repository.list(db)

    def get_user(self, db: Session, user_id: int):
        return self.repository.get(db, user_id)

    def create_user(self, db: Session, payload: UserCreate):
        user = AppUser(**payload.model_dump())
        return self.repository.create(db, user)

    def update_user(self, db: Session, user_id: int, payload: UserUpdate):
        user = self.repository.get(db, user_id)
        if user is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return user
        return self.repository.update(db, user, values)
