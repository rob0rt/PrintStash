"""Snapmaker's provider identity and specialized start contract."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import PrinterProvider
from app.modules.printing.printer_provider import (
    ConfiguredStartProvider,
    MoonrakerProvider,
    ProviderError,
    SnapmakerU1Provider,
    build_provider_registry,
    get_provider_client,
    printer_config_from_model,
)
from app.schemas.printers import SnapmakerU1Start
from tests.factories import printer_config


def test_registry_resolves_snapmaker_to_moonraker_subclass() -> None:
    printer = printer_config(
        "Snapmaker U1",
        provider=PrinterProvider.SNAPMAKER_U1,
        moonraker_url="http://u1.local:7125",
    )
    registry = build_provider_registry()
    client = get_provider_client(printer, registry=registry)
    assert type(client) is SnapmakerU1Provider
    assert isinstance(client, MoonrakerProvider)
    assert isinstance(client, ConfiguredStartProvider)
    assert client.requires_start_options
    assert printer_config_from_model(printer).provider_id.value == "snapmaker_u1"


def test_regular_moonraker_keeps_generic_start_contract() -> None:
    printer = printer_config(
        "Generic Klipper",
        provider=PrinterProvider.MOONRAKER,
        moonraker_url="http://klipper.local:7125",
    )
    client = get_provider_client(printer, registry=build_provider_registry())
    assert type(client) is MoonrakerProvider
    assert isinstance(client, ConfiguredStartProvider)
    assert not client.requires_start_options


@pytest.mark.asyncio
async def test_u1_rejects_legacy_start_without_sending_rpc() -> None:
    provider = SnapmakerU1Provider("http://u1.local:7125")
    provider.client.start_print = AsyncMock()
    with pytest.raises(ProviderError, match="snapmaker_u1_mapping_required"):
        await provider.start("part.gcode")
    provider.client.start_print.assert_not_awaited()


@pytest.mark.asyncio
async def test_u1_configured_start_delegates_to_dedicated_client() -> None:
    provider = SnapmakerU1Provider("http://u1.local:7125")
    provider.client.start_u1_print = AsyncMock(return_value={"state": "ok"})
    options = SnapmakerU1Start(
        mapping=[(0, 2), (1, 3)],
        options={"bed_level": True, "flow_calibrate": False, "time_lapse_camera": True},
    )
    await provider.start_configured("part.gcode", options)
    provider.client.start_u1_print.assert_awaited_once_with(
        "part.gcode", [(0, 2), (1, 3)],
        {"bed_level": True, "flow_calibrate": False, "time_lapse_camera": True},
    )


@pytest.mark.asyncio
async def test_u1_preflight_validates_live_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.printing import snapmaker_u1

    monkeypatch.setattr(
        snapmaker_u1,
        "file_filaments",
        lambda _file, _backend: [{"index": 0, "material": "PETG"}],
    )
    provider = SnapmakerU1Provider("http://u1.local:7125")
    provider.client.query_u1_filaments = AsyncMock(return_value={
        "result": {"status": {"print_task_config": {
            "filament_exist": [True, False, False, False],
            "filament_type": ["PETG", "", "", ""],
        }}},
    })
    options = SnapmakerU1Start(mapping=[(0, 0)])
    await provider.prepare_start(SimpleNamespace(), object(), options)
    with pytest.raises(ProviderError, match="snapmaker_u1_head_empty"):
        await provider.prepare_start(
            SimpleNamespace(), object(),
            SnapmakerU1Start(mapping=[(0, 1)]),
        )
