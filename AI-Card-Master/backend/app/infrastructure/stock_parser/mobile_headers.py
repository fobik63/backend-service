"""iOS / Android User-Agent and header emulation for marketplace mobile APIs."""

from __future__ import annotations

import random
from enum import StrEnum
from typing import Mapping


class MobilePlatform(StrEnum):
    IOS = "ios"
    ANDROID = "android"


_IOS_USER_AGENTS: tuple[str, ...] = (
    "Wildberries/6.5.2000 (iPhone; iOS 17.5.1; Scale/3.00)",
    "Wildberries/6.4.9000 (iPhone; iOS 16.7.2; Scale/3.00)",
    "Ozon/17.42.0 (iPhone; iOS 17.4; Scale/3.00)",
    "OzonApp/17.40.1 CFNetwork/1496.0.7 Darwin/23.5.0",
)

_ANDROID_USER_AGENTS: tuple[str, ...] = (
    "Wildberries/5.78.5000 (Linux; Android 14; Pixel 8 Build/UQ1A)",
    "Wildberries/5.76.3000 (Linux; Android 13; SM-S911B)",
    "ozonapp_android/17.42.0+arm64-v8a (Android 14; Google Pixel 7)",
    "ozonapp_android/17.38.1 (Android 13; samsung SM-A546E)",
)

_WB_IOS_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Deviceid": "ios-emulator",
    "X-Requested-With": "XMLHttpRequest",
}

_WB_ANDROID_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Accept-Language": "ru",
    "Deviceid": "android-emulator",
    "X-Requested-With": "ru.wildberries.client",
}

_OZON_IOS_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Accept-Language": "ru",
    "x-o3-app-name": "ozonapp_ios",
    "x-o3-app-version": "17.42.0",
    "x-o3-fp": "1",
}

_OZON_ANDROID_HEADERS: dict[str, str] = {
    "Accept": "application/json",
    "Accept-Language": "ru",
    "x-o3-app-name": "ozonapp_android",
    "x-o3-app-version": "17.42.0",
    "x-o3-fp": "1",
}


def pick_mobile_platform(*, prefer: MobilePlatform | None = None) -> MobilePlatform:
    if prefer is not None:
        return prefer
    return random.choice((MobilePlatform.IOS, MobilePlatform.ANDROID))


def user_agent_for(
    platform: MobilePlatform,
    *,
    marketplace: str,
) -> str:
    """Pick a marketplace-flavoured mobile User-Agent."""

    pool = _IOS_USER_AGENTS if platform is MobilePlatform.IOS else _ANDROID_USER_AGENTS
    marketplace_key = marketplace.casefold()
    preferred = [
        ua
        for ua in pool
        if (
            ("wildberr" in ua.casefold() and marketplace_key.startswith("wild"))
            or ("ozon" in ua.casefold() and marketplace_key.startswith("ozon"))
        )
    ]
    return random.choice(preferred or pool)


def mobile_headers(
    *,
    marketplace: str,
    platform: MobilePlatform | None = None,
) -> dict[str, str]:
    """Build request headers that mimic WB/Ozon native apps."""

    chosen = pick_mobile_platform(prefer=platform)
    marketplace_key = marketplace.casefold()
    if marketplace_key.startswith("wild"):
        base: Mapping[str, str] = (
            _WB_IOS_HEADERS if chosen is MobilePlatform.IOS else _WB_ANDROID_HEADERS
        )
    else:
        base = (
            _OZON_IOS_HEADERS
            if chosen is MobilePlatform.IOS
            else _OZON_ANDROID_HEADERS
        )
    headers = dict(base)
    headers["User-Agent"] = user_agent_for(chosen, marketplace=marketplace_key)
    return headers
