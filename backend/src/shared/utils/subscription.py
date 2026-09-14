import asyncio
from typing import Tuple

from fastapi import Response

from core.config import settings
from core.factories import (
    get_subscription_service,
    get_remnawave_service,
    get_settings_service,
    get_profiles_service,
    get_users_service,
)
from users.service import UsersService
from settings.service import SettingsService
from profiles.service import ProfilesService
from subscriptions.service import SubscriptionsService
from users.schemas import UserSchema
from shared.exceptions import NotFoundError


async def get_subscription(
    short_uuid: str,
    subscription_service: SubscriptionsService = get_subscription_service(),
    user_service: UsersService = get_users_service(),
    settings_service: SettingsService = get_settings_service(),
) -> Response:
    if settings.RW_ENABLED:
        await _sync_remnawave_user(short_uuid)
    else:
        # Checking if the user exists
        await user_service.get(short_uuid)

    traffic = await user_service.get_traffic(short_uuid)
    if traffic.exceeded:
        return subscription_service.traffic_limit_response(traffic)

    configs, profiles = await _get_running_user_profiles(
        short_uuid=short_uuid
    )

    uris = [
        subscription_service.config_to_uri(
            configs[tag],
            profiles[tag].name,
        )
        for tag in profiles
    ]

    return Response(
        content=subscription_service.prepare_sub_text(
            uris,
            settings_service.get().sub_name,
            traffic.used,
            traffic.limit,
        ),
        media_type="text/plain",
    )


async def _get_running_user_profiles(
    short_uuid: str,
    subscription_service: SubscriptionsService = get_subscription_service(),
    profiles_service: ProfilesService = get_profiles_service(),
) -> Tuple[dict, dict]:
    running_tags = await subscription_service.get_launched_tags(short_uuid)
    loaded = await asyncio.gather(
        *(
            subscription_service.load_config(tag, short_uuid)
            for tag in running_tags
        )
    )

    configs = dict(loaded)

    await asyncio.gather(
        *(
            subscription_service.check_profile(tag, short_uuid, config)
            for tag, config in configs.items()
        )
    )

    profiles_list = await profiles_service.get_all()
    profiles = {
        profile.tag: profile
        for profile in profiles_list
    }
    missing = profiles.keys() - configs.keys()

    await asyncio.gather(
        *(
            subscription_service.start_profile(
                tag=tag,
                short_uuid=short_uuid,
                profiles=profiles,
                configs=configs,
            )
            for tag in missing
        )
    )
    return configs, profiles


async def _sync_remnawave_user(
    short_uuid: str,
    remnawave_service=get_remnawave_service(),
    subscription_service=get_subscription_service(),
    user_service=get_users_service(),
) -> None:
    rw_user = await remnawave_service.get_subscription_info(short_uuid)
    if rw_user is None:
        await subscription_service.remove_user_containers(short_uuid)
        raise NotFoundError
    try:
        await user_service.get(short_uuid)
    except Exception:
        await user_service.add(
            UserSchema(
                short_uuid=short_uuid,
                name=rw_user.user.username,
                expires_at=rw_user.user.expires_at,
            )
        )
