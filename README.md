# greenapi-wa-voip-client-python Library for Python

[![license](https://img.shields.io/badge/license-CC%20BY--ND%204.0-green)](https://creativecommons.org/licenses/by-nd/4.0/)

## Support Links

[![Support](https://img.shields.io/badge/support@green--api.com-D14836?style=for-the-badge&logo=gmail&logoColor=white)](mailto:support@greenapi.com)
[![Support](https://img.shields.io/badge/Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/greenapi_support_eng_bot)
[![Support](https://img.shields.io/badge/WhatsApp-25D366?style=for-the-badge&logo=whatsapp&logoColor=white)](https://wa.me/77273122366)

## Guides & News

[![Guides](https://img.shields.io/badge/YouTube-%23FF0000.svg?style=for-the-badge&logo=YouTube&logoColor=white)](https://www.youtube.com/@greenapi-en)
[![News](https://img.shields.io/badge/Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/green_api)
[![News](https://img.shields.io/badge/WhatsApp-25D366?style=for-the-badge&logo=whatsapp&logoColor=white)](https://whatsapp.com/channel/0029VaLj6J4LNSa2B5Jx6s3h)

- [Документация на русском языке](./docs/README_ru.md)

This library lets a Python 3.11+ application place and receive WhatsApp voice calls through the API service
[green-api.com](https://green-api.com/en/). It talks to the calls API over a WebSocket and carries the audio over WebRTC
using `aiortc`. A microphone and speaker are handled through `sounddevice`. To use it you need an `ID_INSTANCE` and an
`API_TOKEN_INSTANCE` from the [control panel](https://console.green-api.com). The library is free for developers.

The repository ships an interactive command-line client built on the library — see below. It is the place to look first
for an end-to-end usage example.

## The Python client

`run.py` is an interactive call example and the reference usage of this Python library.

It covers what a calls application actually has to do:

- **Credentials** with `idInstance` / `apiTokenInstance`, supplied as arguments or environment variables. The instance
  must already be authorized in the control panel.
- **Dialling** by phone number, chat ID, or LID, for a peer whose number is not known.
- **Incoming calls**: display the caller's name or address, then accept or reject.
- **Local audio**: capture the microphone and play the remote track through system audio.
- **Call commands**: dial, accept, reject, hang up, and stop the local audio bridge.
- **Connection state**, including a reconnect in the middle of a call.

### Running it

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python run.py --api-url https://1234.api.green-api.com \
  --id-instance YOUR_ID --api-token-instance YOUR_TOKEN
```

Installation is needed only the first time. You can also set `GREEN_API_URL`, `ID_INSTANCE`, and `API_TOKEN_INSTANCE`
instead of passing arguments. The client prints `dial <target>`, `accept`, `reject`, `hangup`, `stop`, and `quit`
commands. The instance must already be authorized in the [control panel](https://console.green-api.com/) by scanning the
QR code — this library  deals with calls only. On Linux, `sounddevice` also needs the system PortAudio library and
access to an audio device.

### How it is put together

The parts worth reading first, in the order a call goes through them:

| File | What it holds |
| --- | --- |
| `run.py` | An interactive consumer of the public client, with dial and incoming-call commands |
| `src/__init__.py` | Public package exports, corresponding to the TypeScript `index.ts` |
| `src/green_api_voip_client.py` | REST call commands and `connectCalls()` |
| `src/rest_client.py` | API URL construction and HTTP requests |
| `src/reconnecting_socket.py` | The `callsRtc` WebSocket and reconnect policy |
| `src/calls_connection.py` | Call state, events, signaling, and audio bridge lifecycle |
| `src/rtc/aiortc_bridge.py` | The `aiortc` peer connection and SDP/ICE conversion |
| `src/rtc/audio.py` | Microphone source and speaker output |

Three things in there are not obvious from the API, and each can cause a silent failure if
you get it wrong:

1. **Signalling first, audio second.** `dial()` or `accept()` must resolve before `startAudioBridge()`: the server 
   rejects an offer that belongs to no call.
2. **Subscribe before starting the bridge.** `local-stream-ready` and `remote-stream-ready` may fire before later
   listeners are added. The default audio adapter plays the remote track; use these events if your application needs the
   streams.
3. **Mute is local, and it has to be re-applied.** The track handed out with `local-stream-ready` is the one added to
   the peer connection, so `track.enabled = false` makes the local audio track send silence. After a socket drop
   mid-call the library raises the bridge again with a *new* microphone and without ending the call — a mute set before
   the drop must be put back on the new track.

## Installing the library

Install the library and its Python dependencies from this repository:

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

```python
from greenapi_wa_voip_client import GreenApiVoipClient
```

The package depends on `aiortc`, `httpx`, `websockets`, and `sounddevice`. The examples below run inside an active
`asyncio` event loop; `connectCalls()` starts its WebSocket immediately.

## Using it

The library has two parts. `GreenApiVoipClient` wraps the REST methods — dial, accept, reject, hang up.
`CallsConnection`, returned by `connectCalls()`, holds the WebSocket: it reports the call state, announces incoming
calls, and carries the WebRTC audio.

### Opening the connection

```python
from greenapi_wa_voip_client import GreenApiVoipClient
import asyncio

async def main():
    client = GreenApiVoipClient({
        "idInstance": "your-id-instance",
        "apiTokenInstance": "your-api-token-instance",
        "apiUrl": "your-api-url",  # e.g. https://1234.api.green-api.com
    })

    # Reconnects on its own. The current call state arrives after connecting and
    # on every change, so a restarted process can see an ongoing server call.
    calls = client.connectCalls()
    connected = asyncio.Event()
    calls.addEventListener("connect", lambda event: connected.set())
    calls.addEventListener("disconnect", lambda event: print("Lost:", event.detail["reason"]))
    calls.addEventListener("state", lambda event: print("Call state:", event.detail.state))

    try:
        await connected.wait()
        await asyncio.Event().wait()  # Keep the application running to receive calls.
    finally:
        await calls.close()

asyncio.run(main())
```

### Receiving a call

```python
# Add these listeners inside main(), before waiting for calls.
async def accept_incoming():
    await client.accept()
    await calls.startAudioBridge()

def on_incoming(event):
    info = event.detail
    print("Incoming call from", info.name or info.wid)
    # Show your own UI here; this accepts immediately.
    asyncio.create_task(accept_incoming())

calls.addEventListener("incoming-call", on_incoming)
calls.addEventListener("remote-stream-ready", lambda event: print("Remote audio ready"))
# The default audio adapter plays the remote track through the system speaker.
```

### Placing a call

```python
# Inside main(), after the WebSocket connects: a phone number, a chat ID such as
# 79991234567@c.us, or a LID such as 1062110180230@lid.
await client.dial("79991234567")
await calls.startAudioBridge()
```

A failed bridge does not cancel the call: the server keeps it, and `startAudioBridge()` can be called again. That is
also how audio is reattached after a process restart — if `calls.state.state` is `out-call` or `on-call` and
`calls.hasAudioBridge` is `false`, start the bridge without dialling again. `hasAudioBridge` means a local peer
connection exists; it does not confirm that ICE, DTLS, and RTP are connected.

### Ending a call

```python
await client.hangUp()  # an active call
await client.reject()  # an incoming one

def on_end(event):
    reason = event.detail["reason"]  # 'call-ended' or 'connection-lost'
    cause = event.detail.get("cause")  # 'hangup', 'timeout', 'accepted_elsewhere', …
    print("Call ended:", reason, cause or "")

calls.addEventListener("end-call", on_end)
```

The library tears the audio bridge down itself when a call ends. `await calls.close()` stops the bridge and closes the
socket when you are done with calls altogether.

## Other examples

- [`run.py`](./run.py) — interactive Python calls using this package.
- [Original TypeScript examples](https://github.com/green-api/whatsapp-api-calls-client-js) — browser clients that show
  the signaling flow this port follows.

Run the Python example with `.venv/bin/python run.py --help` for its arguments.

## Documentation

The [Green-API calls documentation](https://green-api.com/docs/calls/) describes the service and call methods. The
original TypeScript repository also has a step-by-step integration guide; the Python installation and usage are shown
above.

## Third-party libraries

The library uses [aiortc](https://aiortc.readthedocs.io/), [httpx](https://www.python-httpx.org/),
[websockets](https://websockets.readthedocs.io/), and [sounddevice](https://python-sounddevice.readthedocs.io/). Their
Python package dependencies are installed by `pip`; PortAudio is a separate system library on Linux.

## License

Licensed under the MIT License. For additional information, see [LICENSE](LICENSE).
