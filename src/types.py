"""Public data shapes from the TypeScript SDK."""

from dataclasses import dataclass
from typing import Literal, Mapping

CallStateKind = Literal["idle", "inc-call", "out-call", "on-call"]


@dataclass(frozen=True)
class CallInfo:
    id: str
    wid: str
    name: str


@dataclass(frozen=True)
class CallState:
    state: CallStateKind
    info: CallInfo | None = None
    reason: str | None = None


@dataclass(frozen=True)
class GreenApiVoipClientOptions:
    idInstance: str
    apiTokenInstance: str
    apiUrl: str


def call_state_from_json(value: Mapping) -> CallState:
    info = value.get("info")
    if isinstance(info, dict):
        info = CallInfo(id=info["id"], wid=info["wid"], name=info["name"])
    else:
        info = None
    return CallState(
        state=value["state"],
        info=info,
        reason=value.get("reason"),
    )
