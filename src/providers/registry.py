"""Provider registry -- creates and holds provider instances."""

from __future__ import annotations

import logging

from src.config import AppConfig
from src.providers.base import Provider
from src.providers.claude import ClaudeProvider
from src.providers.codex import CodexProvider
from src.providers.managed import ManagedProvider

logger = logging.getLogger(__name__)

_FACTORIES: dict[str, type] = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
}


def build_providers(config: AppConfig) -> dict[str, Provider]:
    """Instantiate providers based on configuration."""
    providers: dict[str, Provider] = {}
    for name, provider_config in config.providers.items():
        factory = _FACTORIES.get(name)
        if factory is None:
            logger.error("Unknown provider: %s (available: %s)", name, list(_FACTORIES))
            continue
        providers[name] = ManagedProvider(factory(provider_config))
        logger.info("Registered provider: %s", name)
    return providers
