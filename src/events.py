"""Small synchronous EventTarget equivalent for SDK events."""

import asyncio
import inspect
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Event:
    type: str
    detail: Any = None


class EventTarget:
    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def addEventListener(self, name: str, listener: Callable) -> None:
        if listener not in self._listeners[name]:
            self._listeners[name].append(listener)

    def removeEventListener(self, name: str, listener: Callable) -> None:
        if listener in self._listeners[name]:
            self._listeners[name].remove(listener)

    def dispatchEvent(self, event: Event) -> bool:
        for listener in tuple(self._listeners[event.type]):
            result = listener(event)
            if inspect.isawaitable(result):
                asyncio.get_running_loop().create_task(result)
        return True

    async def _dispatchEventInOrder(self, event: Event) -> None:
        """Finish internal socket handlers before reading the next WS event."""
        for listener in tuple(self._listeners[event.type]):
            try:
                result = listener(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                # An application listener must not turn one frame into a socket
                # failure or prevent later listeners from seeing the frame.
                asyncio.get_running_loop().call_exception_handler({
                    "message": f"Unhandled {event.type} event listener exception",
                    "exception": exc,
                })
