import re
import asyncio
import logging
from typing import NoReturn
from datetime import datetime, timezone

from settings.service import SettingsService
from remnawave.service import RemnawaveService
from users.service import UsersService
from users.schemas import UserSchema


logger = logging.getLogger(__name__)


class RemnawaveSyncManager:
    _task: asyncio.Task | None = None

    def __init__(
        self,
        remnawave_service: RemnawaveService,
        users_service: UsersService,
        settings_service: SettingsService,
    ) -> None:
        self._remnawave_service = remnawave_service
        self._users_service = users_service
        self._settings_service = settings_service

    async def _run(self) -> NoReturn:
        while True:
            try:
                await self.sync_remnawave_users()
                await self._settings_service.update_last_sync(
                    dt=datetime.now(timezone.utc)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SyncManager error")

            try:
                interval_str = self._settings_service.get().sync_interval
                interval = self.parse_interval(interval_str)
            except Exception as e:
                print(e)
                interval = 3600

            await asyncio.sleep(interval)

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    @staticmethod
    def parse_interval(value: str) -> int:
        m = re.fullmatch(r"(\d+)([smh])", value)
        if not m:
            raise ValueError(
                f"Invalid interval format: {value!r}. "
                r"Expected format: number + unit (e.g. 30s, 10m, 4h)"
            )

        num = int(m.group(1))
        if num <= 0:
            raise ValueError(f"Interval must be positive, got {num}")

        unit = m.group(2)
        multipliers = {"s": 1, "m": 60, "h": 3600}
        return num * multipliers[unit]

    async def sync_remnawave_users(self) -> dict[str, int]:
        rw_users = await self._remnawave_service.get_all_users()
        db_users = await self._users_service.get_all()

        rw_map = {
            u.short_uuid: u
            for u in rw_users.users
            if self._remnawave_service.is_user_in_squad(u)
        }

        db_map = {u.short_uuid: u for u in db_users}

        created = 0
        updated = 0
        deleted = 0

        for short_uuid, rw_user in rw_map.items():
            if short_uuid not in db_map:
                await self._users_service.add(
                    UserSchema(
                        short_uuid=rw_user.short_uuid,
                        name=rw_user.username,
                        expires_at=rw_user.expire_at,
                    )
                )
                created += 1
            else:
                db_user = db_map[short_uuid]

                if (
                    db_user.expires_at != rw_user.expire_at
                    or db_user.name != rw_user.username
                ):
                    updated_user = db_user.model_copy(
                        update={
                            "name": rw_user.username,
                            "expires_at": rw_user.expire_at,
                        }
                    )
                    await self._users_service.update(updated_user)
                    updated += 1

        for short_uuid in db_map:
            if short_uuid not in rw_map:
                await self._users_service.delete(short_uuid)
                deleted += 1

        await self._settings_service.update_last_sync(datetime.now(timezone.utc))
        return {
            "created": created,
            "updated": updated,
            "deleted": deleted,
        }
