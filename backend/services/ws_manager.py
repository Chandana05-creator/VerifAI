"""VerifAI — backend/services/ws_manager.py"""
import asyncio
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}
        self._ready: dict[str, asyncio.Event] = {}

    def _event(self, session_id: str) -> asyncio.Event:
        return self._ready.setdefault(session_id, asyncio.Event())

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active[session_id] = websocket
        self._event(session_id).set()

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)
        self._ready.pop(session_id, None)

    async def wait_for_connection(self, session_id: str, timeout: float = 15.0) -> bool:
        """The browser opens its WebSocket right after the POST returns; wait for it so that
        no early events are lost."""
        try:
            await asyncio.wait_for(self._event(session_id).wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def broadcast(self, session_id: str, event: dict):
        ws = self.active.get(session_id)
        if ws is None:
            return
        try:
            await ws.send_json(event)
        except Exception as e:
            print(f"[ws_manager] send failed for {session_id}: {e}")
            self.disconnect(session_id)

    async def keep_alive(self, session_id: str):
        while session_id in self.active:
            await asyncio.sleep(10)
            try:
                await self.active[session_id].send_json({"type": "ping"})
            except Exception:
                break


manager = ConnectionManager()
