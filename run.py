"""Small interactive client for an authorized Green-API instance."""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Sequence

from greenapi_wa_voip_client import GreenApiVoipClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Green-API WhatsApp voice call example")
    parser.add_argument("--api-url", default=os.getenv("GREEN_API_URL"), help="Instance API URL")
    parser.add_argument("--id-instance", default=os.getenv("ID_INSTANCE"), help="Green-API instance ID")
    parser.add_argument("--api-token-instance", default=os.getenv("API_TOKEN_INSTANCE"), help="Green-API instance token")
    parser.add_argument("--dial", help="Phone number, chat ID, or LID to call")
    return parser


async def _run(args) -> int:
    client = GreenApiVoipClient({
        "apiUrl": args.api_url,
        "idInstance": args.id_instance,
        "apiTokenInstance": args.api_token_instance,
    })
    calls = client.connectCalls()
    connected = asyncio.get_running_loop().create_future()
    calls.addEventListener("connect", lambda event: connected.set_result(None) if not connected.done() else None)
    calls.addEventListener("state", lambda event: print("Call state:", event.detail.state))
    calls.addEventListener("incoming-call", lambda event: print("Incoming:", event.detail.name or event.detail.wid))
    calls.addEventListener("end-call", lambda event: print("Call ended:", event.detail))
    calls.addEventListener("error", lambda event: print("Calls error:", event.detail["message"]))
    calls.addEventListener("disconnect", lambda event: print("Calls disconnected:", event.detail["reason"]))
    try:
        await asyncio.wait_for(connected, timeout=20)
        if args.dial:
            await client.dial(args.dial)
            await calls.startAudioBridge()
        print("Commands: dial <target>, accept, reject, hangup, stop, quit")
        while True:
            try:
                command = (await asyncio.to_thread(input, "calls> ")).strip()
            except EOFError:
                break
            if command in ("quit", "exit"):
                break
            try:
                if command.startswith("dial "):
                    await client.dial(command[5:])
                    await calls.startAudioBridge()
                elif command == "accept":
                    await client.accept()
                    await calls.startAudioBridge()
                elif command == "reject":
                    await client.reject()
                elif command == "hangup":
                    await client.hangUp()
                elif command == "stop":
                    await calls.stopAudioBridge()
                elif command:
                    print("Unknown command")
            except Exception as exc:
                print("Command failed:", type(exc).__name__)
    finally:
        await calls.close()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not all((args.api_url, args.id_instance, args.api_token_instance)):
        raise SystemExit("Green-API credentials and API URL are required")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
