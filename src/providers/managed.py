"""Serialize operations that share a CLI credential store."""

from __future__ import annotations

import asyncio

from src.providers.base import AuthStatus, DeviceCodeInfo, Provider, WakeupResult
from src.providers.usage import SubscriptionUsage


class ManagedProvider:
    """Hold one provider lock for a whole login, wake or quota read."""

    def __init__(self, provider: Provider) -> None:
        self._provider = provider
        self._lock = asyncio.Lock()
        self._auth_active = False
        self._auth_control = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._provider.name

    async def check_auth(self) -> AuthStatus:
        async with self._lock:
            return await self._provider.check_auth()

    async def send_wakeup(self) -> WakeupResult:
        async with self._lock:
            return await self._provider.send_wakeup()

    async def read_usage(self) -> SubscriptionUsage:
        async with self._lock:
            return await self._provider.read_usage()

    async def start_device_auth(self) -> DeviceCodeInfo | None:
        async with self._auth_control:
            await self.cancel_device_auth()
            await self._lock.acquire()
            self._auth_active = True
            try:
                result = await self._provider.start_device_auth()
                if result is None:
                    await self.cancel_device_auth()
                return result
            except BaseException:
                await self.cancel_device_auth()
                raise

    async def wait_for_device_auth(self) -> bool:
        try:
            return await self._provider.wait_for_device_auth()
        finally:
            await self.cancel_device_auth()

    async def cancel_device_auth(self) -> None:
        try:
            await self._provider.cancel_device_auth()
        finally:
            if self._auth_active:
                self._auth_active = False
                self._lock.release()
