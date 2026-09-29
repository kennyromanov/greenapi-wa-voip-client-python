"""REST calls and URL construction, matching src/rest-client.ts."""

import json
from dataclasses import asdict, is_dataclass
from typing import Any

import httpx

MISSING = object()


class GreenApiRestClient:
    def __init__(self, options, *, transport=None):
        if is_dataclass(options):
            options = asdict(options)
        self._idInstance = options["idInstance"]
        self._apiTokenInstance = options["apiTokenInstance"]
        self._apiUrl = options["apiUrl"].rstrip("/")
        self._transport = transport

    def buildUrl(self, method: str) -> str:
        return f"{self._apiUrl}/waInstance{self._idInstance}/{method}/{self._apiTokenInstance}"

    def buildWsUrl(self, method: str) -> str:
        url = self.buildUrl(method)
        return "ws" + url[4:] if url.startswith("http") else url

    async def get(self, method: str) -> Any:
        return await self._request(method, "GET")

    async def post(self, method: str, body=MISSING) -> Any:
        return await self._request(method, "POST", body)

    async def _request(self, method: str, verb: str, body=MISSING) -> Any:
        kwargs = {}
        if body is not MISSING:
            kwargs = {"headers": {"Content-Type": "application/json"}, "json": body}
        if self._transport is None:
            async with httpx.AsyncClient() as transport:
                response = await transport.request(verb, self.buildUrl(method), **kwargs)
        else:
            response = await self._transport.request(verb, self.buildUrl(method), **kwargs)
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"{method} failed: {response.status_code} {response.text}")
        if response.status_code == 204 or not response.text:
            return None
        return json.loads(response.text)
