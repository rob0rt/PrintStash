"""Snapmaker U1's custom start RPC stays out of generic Moonraker."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from printstash_core.printers.models import SnapmakerU1Config
from printstash_core.printers.moonraker import MoonrakerError
from printstash_core.printers.snapmaker_u1 import SnapmakerU1Client


class ScriptedSocket:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.sent: list[dict[str, Any]] = []

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        if not self.responses:
            raise asyncio.TimeoutError
        return json.dumps(self.responses.pop(0))


def _client(socket: ScriptedSocket, api_key: str | None = None) -> SnapmakerU1Client:
    class Connector:
        async def __aenter__(self) -> ScriptedSocket:
            return socket

        async def __aexit__(self, *_args: object) -> None:
            return None

    return SnapmakerU1Client(
        SnapmakerU1Config("http://u1.local:7125", api_key=api_key),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _req: httpx.Response(
                    200, json={"result": {"status": {"print_task_config": {}}}}
                )
            )
        ),
        websocket_connector=lambda *_args, **_kwargs: Connector(),
        timeout=1.0,
    )


@pytest.mark.asyncio
async def test_custom_start_uses_u1_rpc_and_maps_four_head_indices() -> None:
    socket = ScriptedSocket(
        {"jsonrpc": "2.0", "method": "notify_status_update", "params": []},
        {"jsonrpc": "2.0", "id": 1, "result": {"state": "ok"}},
    )
    client = _client(socket)
    try:
        result = await client.start_u1_print(
            "my-part.gcode",
            [(0, 2), (1, 3)],
            {"bed_level": True, "flow_calibrate": False, "time_lapse_camera": True},
        )
    finally:
        await client.aclose()
    assert result["state"] == "ok"
    assert socket.sent == [{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "server.files.start_local_print",
        "params": {
            "type": "gcode",
            "path": "my-part.gcode",
            "options": {
                "map_table": [[0, 2], [1, 3]],
                "bed_level": 1,
                "flow_calibrate": 0,
                "time_lapse_camera": 1,
            },
        },
    }]


@pytest.mark.asyncio
async def test_identifies_when_key_is_configured() -> None:
    socket = ScriptedSocket(
        {"id": 1, "result": {"connection_id": 9}},
        {"id": 2, "result": {"state": "ok"}},
    )
    client = _client(socket, api_key="fake-key")
    try:
        await client.start_u1_print(
            "part.gcode", [(0, 0)],
            {"bed_level": False, "flow_calibrate": False, "time_lapse_camera": False},
        )
    finally:
        await client.aclose()
    assert socket.sent[0]["method"] == "server.connection.identify"
    assert socket.sent[0]["params"]["api_key"] == "fake-key"
    assert socket.sent[1]["id"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {"id": 1, "error": {"code": -32600, "message": "failed"}},
    {"id": 1, "result": {"state": "error", "message": "wrong filament"}},
    {"id": 1, "result": None},
])
async def test_rejected_start_is_never_reported_as_success(response: dict[str, Any]) -> None:
    client = _client(ScriptedSocket(response))
    try:
        with pytest.raises(MoonrakerError, match="snapmaker_u1_"):
            await client.start_u1_print(
                "part.gcode", [(0, 0)],
                {"bed_level": True, "flow_calibrate": False, "time_lapse_camera": False},
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../escape.gcode", "/absolute.gcode", "a.gcode/../b.gcode", "part.bgcode"])
async def test_rejects_invalid_remote_paths(filename: str) -> None:
    client = _client(ScriptedSocket())
    try:
        with pytest.raises(MoonrakerError, match="invalid_path"):
            await client.start_u1_print(
                filename, [(0, 0)],
                {"bed_level": True, "flow_calibrate": False, "time_lapse_camera": False},
            )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_filament_snapshot_endpoint() -> None:
    client = _client(ScriptedSocket())
    try:
        response = await client.query_u1_filaments()
    finally:
        await client.aclose()
    assert response["result"]["status"]["print_task_config"] == {}
