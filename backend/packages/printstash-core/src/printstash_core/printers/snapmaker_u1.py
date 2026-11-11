"""Snapmaker U1-specific Moonraker extensions.

The generic Moonraker client remains unaware of vendor print-start methods.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any, cast

from .models import SnapmakerU1Config
from .moonraker import MoonrakerClient, MoonrakerError


class SnapmakerU1Client(MoonrakerClient):
    """U1 custom commands, inheriting standard Moonraker monitoring and upload."""

    def __init__(self, config: SnapmakerU1Config, **kwargs: Any) -> None:
        super().__init__(config, **kwargs)

    async def query_u1_filaments(self) -> dict[str, Any]:
        """Read the U1-specific four-slot filament snapshot."""
        return await self._request("GET", "/printer/objects/query?print_task_config")

    async def start_u1_print(
        self,
        remote_filename: str,
        mapping: list[tuple[int, int]],
        options: Mapping[str, bool],
    ) -> dict[str, Any]:
        """Start a U1 job with firmware mapping/preferences over Moonraker JSON-RPC.

        The caller must have uploaded the file with `print=false`. Never replay
        this command on a timeout: the printer may have accepted it.
        """
        if not remote_filename or remote_filename.startswith("/") or "\\" in remote_filename:
            raise MoonrakerError("snapmaker_u1_invalid_path")
        if any(part in {"", ".", ".."} for part in remote_filename.split("/")):
            raise MoonrakerError("snapmaker_u1_invalid_path")
        if not remote_filename.lower().endswith(".gcode"):
            raise MoonrakerError("snapmaker_u1_invalid_path")

        async with self._websocket_connector(self._ws_url(), max_size=8 * 1024 * 1024) as ws:
            request_id = 1
            if self.api_key:
                await ws.send(json.dumps({
                    "jsonrpc": "2.0", "id": request_id,
                    "method": "server.connection.identify",
                    "params": {
                        "client_name": "PrintStash", "version": "1",
                        "type": "agent", "url": "https://printstash.io",
                        "api_key": self.api_key,
                    },
                }))
                auth = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.timeout))
                if auth.get("id") != request_id or "error" in auth:
                    raise MoonrakerError("snapmaker_u1_authentication_failed")
                request_id += 1

            await ws.send(json.dumps({
                "jsonrpc": "2.0", "id": request_id,
                "method": "server.files.start_local_print",
                "params": {
                    "type": "gcode",
                    "path": remote_filename,
                    "options": {
                        "map_table": [[logical, physical] for logical, physical in mapping],
                        "bed_level": int(options["bed_level"]),
                        "flow_calibrate": int(options["flow_calibrate"]),
                        "time_lapse_camera": int(options["time_lapse_camera"]),
                    },
                },
            }))
            # Other Moonraker notifications can interleave with the RPC response.
            while True:
                response = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.timeout))
                if response.get("id") != request_id:
                    continue
                if "error" in response:
                    raise MoonrakerError("snapmaker_u1_start_rejected")
                result = response.get("result")
                if isinstance(result, Mapping) and result.get("state") == "error":
                    raise MoonrakerError("snapmaker_u1_start_rejected")
                if result is None:
                    raise MoonrakerError("snapmaker_u1_invalid_start_response")
                return cast(dict[str, Any], result) if isinstance(result, dict) else {"result": result}

