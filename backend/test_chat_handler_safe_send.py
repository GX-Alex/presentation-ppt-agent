import asyncio
import time

from starlette.websockets import WebSocketState

from app.ws.chat_handler import _WebSocketSafeSender


class _RecordingWebSocket:
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.messages: list[dict] = []

    async def send_json(self, msg: dict) -> None:
        self.messages.append(msg)


class _HangingWebSocket:
    def __init__(self):
        self.client_state = WebSocketState.CONNECTED
        self.calls = 0

    async def send_json(self, msg: dict) -> None:
        self.calls += 1
        await asyncio.sleep(3600)


def test_safe_sender_delivers_while_connected() -> None:
    async def scenario() -> None:
        websocket = _RecordingWebSocket()
        sender = _WebSocketSafeSender(websocket, send_timeout_seconds=0.1)

        await sender.send({"type": "status", "text": "ok"})

        assert websocket.messages == [{"type": "status", "text": "ok"}]

    asyncio.run(scenario())


def test_safe_sender_times_out_once_and_stops_blocking() -> None:
    async def scenario() -> None:
        websocket = _HangingWebSocket()
        sender = _WebSocketSafeSender(websocket, send_timeout_seconds=0.05)

        started = time.monotonic()
        await sender.send({"type": "webdeck_page_ready"})
        elapsed = time.monotonic() - started

        await sender.send({"type": "webdeck_complete"})

        assert elapsed < 0.3
        assert websocket.calls == 1

    asyncio.run(scenario())