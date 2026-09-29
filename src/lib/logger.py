"""Python counterpart of the optional TS Logger."""

import json
import logging
import os


def isDebugLogEnabled() -> bool:
    return os.environ.get("WA_LOG_DEBUG") == "1"


def j(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


class Logger:
    def __init__(self, prefix: str = "", style=None):
        self._prefix = prefix
        self._style = dict(style or {})
        self._logger = logging.getLogger("greenapi_wa_voip_client")

    def _message(self, message: str, args) -> str:
        suffix = " " + " ".join(map(str, args)) if args else ""
        return f"{self._prefix} {message}{suffix}".strip()

    def info(self, message: str, *args) -> None:
        self._logger.info(self._message(message, args))

    def warn(self, message: str, *args) -> None:
        self._logger.warning(self._message(message, args))

    def error(self, message: str, *args) -> None:
        self._logger.error(self._message(message, args))

    def debug(self, message: str, *args) -> None:
        if isDebugLogEnabled():
            self._logger.debug(self._message(message, args))

    def logDebugIfEnabled(self, fn) -> None:
        if isDebugLogEnabled():
            result = fn()
            if isinstance(result, (tuple, list)):
                self.debug(result[0], *result[1:])
            else:
                self.debug(result)

    def log(self, message: str, *args) -> None:
        self.info(message, *args)

    def child(self, prefix: str, style=None):
        return Logger(f"{self._prefix} {prefix}".strip(), {**self._style, **(style or {})})

    @property
    def isDebugEnabled(self) -> bool:
        return isDebugLogEnabled()
