import asyncio
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

HEARTBEAT_INTERVAL = 1  # seconds


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.game_id = int(self.scope["url_route"]["kwargs"]["game_id"])
        self.group_name = f"game_{self.game_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        state = await database_sync_to_async(self._get_state)()
        await self.send(text_data=json.dumps(state))
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat_loop())

    def _get_state(self):
        from host.views import _get_display_game, _serialize_game_state

        game = _get_display_game(game_id=self.game_id)
        return _serialize_game_state(game)

    async def _heartbeat_loop(self):
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await self.send(text_data=json.dumps({"heartbeat": True}))
        except asyncio.CancelledError:
            pass

    async def disconnect(self, close_code):
        self._heartbeat_task.cancel()
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass

    async def game_state_update(self, event):
        await self.send(text_data=json.dumps(event["state"]))
