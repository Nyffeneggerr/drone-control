"""FastAPI server: serves the PWA and bridges browser <-> MAVLink over one WebSocket.

Protocol (JSON messages over /ws):

Client -> server:
  {"type": "control", "x": -1000..1000, "y": -1000..1000, "z": 0..1000, "r": -1000..1000}
  {"type": "arm"}
  {"type": "disarm"}
  {"type": "mode", "mode": "GUIDED"}

Server -> client:
  {"type": "telemetry", "armed": bool, "mode": str, "link_ok": bool,
   "battery_voltage": float|null, "battery_remaining": int|null,
   "gps_fix_type": int, "satellites_visible": int,
   "lat": float|null, "lon": float|null, "alt": float|null}
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from mavlink_bridge import GPS_FIX_TYPE_3D, MavlinkBridge, Telemetry

FC_PORT = os.environ.get("FC_PORT", "/dev/serial0")
FC_BAUD = int(os.environ.get("FC_BAUD", "57600"))
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI()

_bridge: MavlinkBridge | None = None
_subscribers: set[asyncio.Queue] = set()
_main_loop: asyncio.AbstractEventLoop | None = None


def _broadcast_telemetry(telemetry: Telemetry) -> None:
    # called from the bridge's own thread -> hop back onto the asyncio loop
    if _main_loop is None:
        return
    payload = {"type": "telemetry", **asdict(telemetry)}
    for queue in list(_subscribers):
        _main_loop.call_soon_threadsafe(queue.put_nowait, payload)


@app.on_event("startup")
async def startup() -> None:
    global _bridge, _main_loop
    _main_loop = asyncio.get_running_loop()
    _bridge = MavlinkBridge(FC_PORT, FC_BAUD, on_telemetry=_broadcast_telemetry)
    _bridge.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    if _bridge:
        _bridge.stop()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.add(queue)

    async def reader() -> None:
        while True:
            raw = await websocket.receive_text()
            _handle_client_message(raw)

    async def writer() -> None:
        while True:
            payload = await queue.get()
            await websocket.send_text(json.dumps(payload))

    try:
        await asyncio.gather(reader(), writer())
    except WebSocketDisconnect:
        pass
    finally:
        _subscribers.discard(queue)


def _handle_client_message(raw: str) -> None:
    assert _bridge is not None
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return

    msg_type = msg.get("type")
    if msg_type == "control":
        _bridge.set_control(
            x=int(msg.get("x", 0)),
            y=int(msg.get("y", 0)),
            z=int(msg.get("z", 0)),
            r=int(msg.get("r", 0)),
        )
    elif msg_type == "arm":
        if _bridge.get_telemetry().gps_fix_type < GPS_FIX_TYPE_3D:
            return  # app-layer refusal per PRD; bridge also refuses independently
        _bridge.request_arm()
    elif msg_type == "disarm":
        _bridge.request_disarm()
    elif msg_type == "mode":
        mode = msg.get("mode")
        if mode:
            _bridge.request_mode(mode)


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
