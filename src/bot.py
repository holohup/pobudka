"""Telegram bot for user communication and auth flow orchestration."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
import logging
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.config import AppConfig, load_config
from src.providers.base import AuthStatus, Provider

if TYPE_CHECKING:
    from src.scheduler import WakeupScheduler

logger = logging.getLogger(__name__)
_ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
_WAKE_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


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

        logger.info("Manual wake requested for provider=%s", provider_name)
        result = await self._scheduler.trigger_wakeup(provider_name)
        if result is None:
            logger.warning("Manual wake failed: unknown provider=%s", provider_name)
            return f"Unknown provider: {provider_name}"

        state = self._scheduler.get_state(provider_name)
        next_run = "unknown" if state is None else state.next_run_at.isoformat()

        if result.success:
            logger.info(
                "Manual wake succeeded for provider=%s next_run=%s",
                provider_name,
                next_run,
            )
            return f"{provider_name}: wake-up succeeded.\nNext run: {next_run}"

        logger.warning(
            "Manual wake failed for provider=%s kind=%s message=%s",
            provider_name,
            result.failure_kind.value,
            result.message[:200],
        )
        return (
            f"{provider_name}: wake-up failed ({result.failure_kind.value}).\n"
            f"Message: {result.message}\n"
            f"Next run: {next_run}"
        )

    async def schedule_wake_at_israel_time(
        self,
        provider_name: str,
        time_text: str,
    ) -> str:
        """Schedule next wake-up at HH:MM Israel time."""
        if self._scheduler is None:
            return "Scheduler is not initialized yet."

        try:
            refreshed_config = load_config()
        except RuntimeError as exc:
            logger.exception("Failed to reload config for scheduled wake")
            return f"Config reload failed: {exc}"

        provider_config = refreshed_config.providers.get(provider_name)
        if provider_config is None:
            return f"Unknown provider: {provider_name}"

        if not self._scheduler.reload_provider_config(provider_name, provider_config):
            return f"Unknown provider: {provider_name}"

        try:
            target_utc, next_day = self._next_israel_occurrence(time_text)
        except ValueError as exc:
            return str(exc)

        state = await self._scheduler.schedule_next_wakeup(provider_name, target_utc)
        if state is None:
            return f"Unknown provider: {provider_name}"

        target_il = target_utc.astimezone(_ISRAEL_TZ)
        day_note = " (next day)" if next_day else ""
        return (
            f"{provider_name}: next reset scheduled for "
            f"{target_il.strftime('%Y-%m-%d %H:%M:%S %Z')}{day_note}.\n"
            f"UTC: {target_utc.strftime('%Y-%m-%d %H:%M:%SZ')}"
        )

    def _next_israel_occurrence(self, time_text: str) -> tuple[datetime, bool]:
        """Return next occurrence of HH:MM in Israel timezone as UTC."""
        raw = time_text.strip()
        if not _WAKE_TIME_RE.fullmatch(raw):
            raise ValueError(
                "Invalid time format. Use HH:MM in Israel time, e.g. /wake codex 12:00"
            )

        hour, minute = (int(part) for part in raw.split(":"))
        now_utc = datetime.now(timezone.utc)
        now_il = now_utc.astimezone(_ISRAEL_TZ)
        target_il = now_il.replace(hour=hour, minute=minute, second=0, microsecond=0)
        next_day = target_il <= now_il
        if next_day:
            target_il = target_il + timedelta(days=1)
        return target_il.astimezone(timezone.utc), next_day

    def _commands_text(self) -> str:
        return (
            "<b>Pobudka Commands</b>\n\n"
            "/status - Show all provider auth status\n"
            "/auth &lt;provider&gt; - Start device-code auth\n"
            "/check_auth [provider] - Verify auth status\n"
            "/schedule - Show scheduler state\n"
            "/wake &lt;provider&gt; - Trigger immediate wake-up\n"
            "/wake &lt;provider&gt; HH:MM - Schedule next wake in Israel time\n"
            "/menu - Show command menu\n"
            "/help - Show command menu\n"
            "/start - Show command menu"
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
            await self.send(self._auth_fallback_message(provider_name, provider.name))
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

    def _auth_fallback_message(self, provider_name: str, provider_label: str) -> str:
        """Build provider-specific fallback instructions."""
        if provider_name == "claude":
            return (
                f"Could not start device-code flow for {provider_label}.\n\n"
                "<b>Fallback:</b> this Claude CLI version does not expose a "
                "non-interactive device command.\n"
                "Run interactive setup inside the container:\n"
                "<code>docker compose exec -it pobudka claude setup-token</code>\n"
                "Then run:\n"
                "<code>/check_auth claude</code>"
            )

        if provider_name == "codex":
            return (
                f"Could not start device-code flow for {provider_label}.\n\n"
                "<b>Fallback:</b> run interactive auth inside the container:\n"
                "<code>docker compose exec -it pobudka codex login --device-auth</code>\n"
                "Then run:\n"
                "<code>/check_auth codex</code>"
            )

        return (
            f"Could not start device-code flow for {provider_label}.\n\n"
            "<b>Fallback:</b> authenticate on a machine with a browser, then copy "
            "auth files to Docker volume and run:\n"
            f"<code>/check_auth {provider_name}</code>"
        )

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
            await message.reply(bot_ref._commands_text(), parse_mode="HTML")

        @self._router.message(Command("menu"))
        async def cmd_menu(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            await message.reply(bot_ref._commands_text(), parse_mode="HTML")

        @self._router.message(Command("start"))
        async def cmd_start(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            await message.reply(bot_ref._commands_text(), parse_mode="HTML")

        @self._router.message(Command("schedule"))
        async def cmd_schedule(message: Message) -> None:
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                return
            await message.reply(await bot_ref.get_schedule_text(), parse_mode="HTML")

        @self._router.message(Command("wake"))
        async def cmd_wake(message: Message) -> None:
            logger.info(
                "Received /wake command chat_id=%s text=%r",
                message.chat.id,
                message.text,
            )
            if str(message.chat.id) != bot_ref._config.telegram.chat_id:
                logger.warning(
                    "Ignoring /wake from unauthorized chat_id=%s expected=%s",
                    message.chat.id,
                    bot_ref._config.telegram.chat_id,
                )
                return

            parts = (message.text or "").split()
            if len(parts) < 2:
                names = ", ".join(bot_ref._providers.keys())
                await message.reply(
                    "Usage:\n"
                    "/wake <provider>\n"
                    "/wake <provider> HH:MM (Israel time)\n"
                    f"Available: {names}"
                )
                return

            provider_name = parts[1].lower()
            if len(parts) == 2:
                await message.reply(await bot_ref.run_manual_wake(provider_name))
                return

            if len(parts) == 3:
                await message.reply(
                    await bot_ref.schedule_wake_at_israel_time(provider_name, parts[2])
                )
                return

            await message.reply(
                "Usage:\n"
                "/wake <provider>\n"
                "/wake <provider> HH:MM (Israel time)"
            )
