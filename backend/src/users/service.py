from fastapi import HTTPException, status

from settings.service import SettingsService
from users.repository import UserRepository
from users.schemas import UserSchema, TrafficInfoSchema


class UsersService:
    def __init__(
        self,
        repo: UserRepository,
        settings_service: SettingsService,
    ) -> None:
        self._repo = repo
        self._settings_service = settings_service

    async def add(self, user: UserSchema) -> UserSchema:
        new_user = await self._repo.add_user(user.model_dump())
        return UserSchema(**new_user)

    async def exists(self, short_uuid: str) -> bool:
        return await self._repo.is_user_exists(short_uuid)

    async def get(self, short_uuid: str) -> UserSchema:
        user = await self._repo.get_user(short_uuid)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return UserSchema(**user)

    async def update(self, user: UserSchema) -> None:
        await self._repo.update_user(user.model_dump())

    async def delete(self, short_uuid: str) -> None:
        await self._repo.delete_user(short_uuid)

    async def get_all(self) -> list[UserSchema]:
        users = await self._repo.get_all_users()
        if users is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Users not found",
            )
        return [UserSchema(**user) for user in users]

    async def get_traffic(self, short_uuid: str) -> TrafficInfoSchema:
        user = await self.get(short_uuid)
        unlimited = user.traffic_limit_bytes == 0
        remaining = 0 if unlimited else max(
            0, user.traffic_limit_bytes - user.traffic_used_bytes)
        exceeded = (
            not unlimited) and user.traffic_used_bytes >= user.traffic_limit_bytes
        return TrafficInfoSchema(
            short_uuid=short_uuid,
            limit=user.traffic_limit_bytes,
            used=user.traffic_used_bytes,
            remaining=remaining,
            unlimited=unlimited,
            exceeded=exceeded,
        )

    async def set_traffic_limit(self, short_uuid: str, limit: int) -> None:
        await self._repo.set_traffic_limit(short_uuid, limit)

    async def reset_traffic(self, short_uuid: str) -> None:
        await self._repo.reset_traffic(short_uuid)

    async def add_traffic_used(self, short_uuid: str, delta: int) -> None:
        if delta <= 0:
            return
        await self._repo.update_traffic_used(short_uuid, delta)
