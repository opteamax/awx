"""Connects to daphne's /websocket/relay/ with aiohttp the way awx.main.wsrelay does."""
import asyncio
import sys

import aiohttp
import django

django.setup()

from awx.main.consumers import WebsocketSecretAuthHelper  # noqa: E402

URI = 'ws://127.0.0.1:8051/websocket/relay/'


async def connect(secret):
    async with aiohttp.ClientSession(headers={'secret': secret}, timeout=aiohttp.ClientTimeout(total=10)) as session:
        try:
            async with session.ws_connect(URI, heartbeat=20) as ws:
                await ws.send_json({'group': 'smoke', 'message': '{}'})
                await ws.close()
                return True
        except aiohttp.WSServerHandshakeError:
            return False


async def main():
    ok = await connect(WebsocketSecretAuthHelper.construct_secret())
    print(('PASS' if ok else 'FAIL') + ' wsrelay connect with valid secret (aiohttp)')
    rejected = not await connect('HMAC-SHA256 1:invalid')
    print(('PASS' if rejected else 'FAIL') + ' wsrelay rejects invalid secret')
    return ok and rejected


sys.exit(0 if asyncio.run(main()) else 1)
