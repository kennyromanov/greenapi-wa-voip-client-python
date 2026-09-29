"""Public REST facade from src/green-api-voip-client.ts."""

from .calls_connection import CallsConnection
from .rest_client import GreenApiRestClient
from .types import call_state_from_json


def dialTargetToChatId(target: str) -> str:
    return target if "@" in target else f"{target}@c.us"


class GreenApiVoipClient:
    def __init__(self, options):
        self._rest = GreenApiRestClient(options)

    async def getCallState(self):
        return call_state_from_json(await self._rest.get("callsState"))

    async def getIceServers(self):
        return await self._rest.get("callsGetIceServers")

    async def dial(self, target: str) -> None:
        await self._rest.post("callsDial", {"chatId": dialTargetToChatId(target)})

    async def accept(self) -> None:
        await self._rest.post("callsAccept")

    async def reject(self) -> None:
        await self._rest.post("callsReject")

    async def hangUp(self) -> None:
        await self._rest.post("callsHangUp")

    def connectCalls(self) -> CallsConnection:
        return CallsConnection(self._rest)
