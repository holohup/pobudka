"""Pobudka -- keep LLM providers awake and tokens ready."""

from __future__ import annotations

import asyncio
import logging
import sys

from src.bot import TelegramBot
from src.config import load_config
from src.providers.base import AuthStatus
from src.providers.registry import build_providers
from src.scheduler import WakeupScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def startup_auth_check(bot: TelegramBot) -> None:
    """Check auth for all providers on startup and notify via Telegram."""
    results = await bot.check_all_auth()

    lines = ["Pobudka started. Auth status:\n"]
    needs_auth: list[str] = []

    for name, status in results.items():
        lines.append(f"  {name}: {status.name}")
        if status != AuthStatus.OK:
            needs_auth.append(name)

    if needs_auth:
        lines.append("\nUse /auth &lt;provider&gt; to attempt authentication manually.")

    await bot.send("\n".join(lines))


async def main() -> None:
    logger.info("Loading configuration")
    try:
        config = load_config()
    except RuntimeError as exc:
        logger.critical("Configuration error: %s", exc)
        sys.exit(1)

    logger.info(
        "Enabled providers: %s",
        ", ".join(config.providers.keys()),
    )

    providers = build_providers(config)
    if not providers:
        logger.critical("No providers configured")
        sys.exit(1)

    bot = TelegramBot(config, providers)
    scheduler = WakeupScheduler(
        config=config,
        providers=providers,
        notify=bot.send,
        request_auth=bot.run_device_auth,
    )
    bot.set_scheduler(scheduler)

    try:
        await startup_auth_check(bot)
        await scheduler.start()
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        await scheduler.stop()
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
