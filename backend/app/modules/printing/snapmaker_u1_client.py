"""Application HTTP pooling for the dedicated Snapmaker U1 transport."""

from __future__ import annotations

from typing import Optional, cast

from printstash_core.printers.models import SnapmakerU1Config
from printstash_core.printers.moonraker import HttpClientFactory
from printstash_core.printers.snapmaker_u1 import SnapmakerU1Client as _CoreSnapmakerU1Client

from app.modules.printing.moonraker import _dynamic_http_client_factory, logger


class SnapmakerU1Client(_CoreSnapmakerU1Client):
    """Keep Moonraker's shared HTTP client pooling for the U1 adapter."""

    def __init__(
        self, base_url: str, api_key: Optional[str] = None, *, timeout: float = 30.0
    ) -> None:
        super().__init__(
            SnapmakerU1Config(base_url, api_key),
            timeout=timeout,
            http_client_factory=cast(HttpClientFactory, _dynamic_http_client_factory),
            logger=logger,
        )
