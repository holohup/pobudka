"""Telegram bot for user communication and auth flow orchestration."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.config import AppConfig
from src.providers.base import AuthStatus, Provider

if TYPE_CHECKING:
    from src.scheduler import WakeupScheduler

logger = logging.getLogger(__name__)


class TelegramBot:
    """Manages the Telegram bot and provider auth flows."""

    def __init__(self, config: AppConfig, providers: dict[str, Provider]) -> None:
        self._config = config
        self._providers = providers
        self._bot = Bot(token=config.telegram.bot_token)
        self._dp = Dispatcher()
        self._router = Router()
        self._dp.include_router(self._router)
        self._pending_auth: dict[str, asyncio.Task[bool]] = {}
        self._scheduler: WakeupScheduler | None = None

        # Register handlers with access to self
        self._register_handlers()

    @property
    def bot(self) -> Bot:
        return self._bot

    async def start(self) -> None:
        """Start polling for Telegram updates."""
        logger.info("Starting Telegram bot")
        await self._dp.start_polling(self._bot)

    async def stop(self) -> None:
        """Stop the bot and cancel pending auth flows."""
        for task in self._pending_auth.values():
            task.cancel()
        self._pending_auth.clear()
        await self._bot.session.close()

    def set_scheduler(self, scheduler: "WakeupScheduler") -> None:
        """Attach the scheduler used by bot command handlers."""
        self._scheduler = scheduler

    async def send(self, text: str) -> None:
        """Send a message to the configured chat."""
        await self._bot.send_message(
            chat_id=self._config.telegram.chat_id,
            text=text,
            parse_mode="HTML",
        )

    async def get_schedule_text(self) -> str:
        """Return scheduler status text for `/schedule`."""
        if self._scheduler is None:
            return "Scheduler is not initialized yet."
        return self._scheduler.format_status()

    async def run_manual_wake(self, provider_name: str) -> str:
        """Trigger a wake-up and return a status message for `/wake`."""
        if self._scheduler is None:
            return "Scheduler is not initialized yet."

        result = await self._scheduler.trigger_wakeup(provider_name)
        if result is None:
            return f"Unknown provider: {provider_name}"

        state = self._scheduler.get_state(provider_name)
        next_run = "unknown" if state is None else state.next_run_at.isoformat()

        if result.success:
            return f"{provider_name}: wake-up succeeded.\nNext run: {next_run}"

        return (
            f"{provider_name}: wake-up failed ({result.failure_kind.value}).\n"
            f"Message: {result.message}\n"
            f"Next run: {next_run}"
        )

    async def check_all_auth(self) -> dict[str, AuthStatus]:
        """Check auth status for all providers and return results."""
        results: dict[str, AuthStatus] = {}
        for name, provider in self._providers.items():
            status = await provider.check_auth()
            results[name] = status
        return results

    async def run_device_auth(self, provider_name: str) -> None:
        """Orchestrate device-code auth for a provider via Telegram."""
        provider = self._providers.get(provider_name)
        if provider is None:
            await self.send(f"Unknown provider: {provider_name}")
            return

        # Cancel any existing auth flow for this provider
        if provider_name in self._pending_auth:
            self._pending_auth[provider_name].cancel()

        await self.send(f"Starting device-code auth for {provider.name}...")

        info = await provider.start_device_auth()
        if info is None:
            await self.send(
                f"Could not start device-code flow for {provider.name}.\n\n"
                f"<b>Fallback:</b> Authenticate on a machine with a browser, "
                f"then copy the auth files to the Docker volume.\n"
                f"Use /check_auth {provider_name} after copying."
            )
            return

        await self.send(
            f"<b>{provider.name} authentication required</b>\n\n"
            f"1. Open: {info.url}\n"
            f"2. Enter code: <code>{info.code}</code>\n\n"
            f"Waiting for you to complete authentication..."
        )

        # Wait for completion in the background
        async def _wait() -> bool:
            success = await provider.wait_for_device_auth()
            if success:
                await self.send(f"{provider.name} authentication successful!")
            else:
                await self.send(
                    f"{provider.name} authentication timed out or failed.\n"
                    f"Use /auth {provider_name} to try again."
                )
            return success

        self._pending_auth[provider_name] = asyncio.create_task(_wait())

    def _register_handlers(self) -> None:
        """Register Telegram command handlers."""
        bot_ref = self

        @self._router.message(Command("status"))
        async def cmd_status(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            results = await bot_ref.check_all_auth()
            lines = ["<b>Provider Status</b>\n"]
            for name, status in results.items():
                icon = {
                    AuthStatus.OK: "OK",
                    AuthStatus.NOT_AUTHENTICATED: "NOT AUTH",
                    AuthStatus.EXPIRED: "EXPIRED",
                    AuthStatus.ERROR: "ERROR",
                }[status]
                lines.append(f"  {name}: {icon}")
            await message.reply("\n".join(lines), parse_mode="HTML")

        @self._router.message(Command("auth"))
        async def cmd_auth(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            parts = (message.text or "").split()
            if len(parts) < 2:
                names = ", ".join(bot_ref._providers.keys())
                await message.reply(f"Usage: /auth <provider>\nAvailable: {names}")
                return
            provider_name = parts[1].lower()
            await bot_ref.run_device_auth(provider_name)

        @self._router.message(Command("check_auth"))
        async def cmd_check_auth(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            parts = (message.text or "").split()
            if len(parts) < 2:
                # Check all
                results = await bot_ref.check_all_auth()
                lines = []
                for name, status in results.items():
                    lines.append(f"{name}: {status.name}")
                await message.reply("\n".join(lines))
                return

            provider_name = parts[1].lower()
            provider = bot_ref._providers.get(provider_name)
            if provider is None:
                await message.reply(f"Unknown provider: {provider_name}")
                return

            status = await provider.check_auth()
            await message.reply(f"{provider.name}: {status.name}")

        @self._router.message(Command("help"))
        async def cmd_help(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            await message.reply(
                "<b>Pobudka Commands</b>\n\n"
                "/status - Show all provider auth status\n"
                "/auth &lt;provider&gt; - Start device-code auth\n"
                "/check_auth [provider] - Verify auth status\n"
                "/schedule - Show scheduler state\n"
                "/wake &lt;provider&gt; - Trigger immediate wake-up\n"
                "/help - Show this message",
                parse_mode="HTML",
            )

        @self._router.message(Command("schedule"))
        async def cmd_schedule(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            await message.reply(await bot_ref.get_schedule_text(), parse_mode="HTML")

        @self._router.message(Command("wake"))
        async def cmd_wake(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return

            parts = (message.text or "").split()
            if len(parts) < 2:
                names = ", ".join(bot_ref._providers.keys())
                await message.reply(f"Usage: /wake <provider>\nAvailable: {names}")
                return

            provider_name = parts[1].lower()
            await message.reply(await bot_ref.run_manual_wake(provider_name))
