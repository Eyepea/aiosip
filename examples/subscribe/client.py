import argparse
import asyncio
import contextlib
import logging
import random

import aiosip

REMOTE_ADDR = ('127.0.0.1', 5060)
LOCAL_ADDR = ('127.0.0.1', 5080)
USER = 'subscriber'


async def run_subscription(peer, duration):
    subscription = await peer.subscribe(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            USER, *LOCAL_ADDR)),
        to_details=aiosip.Contact.from_header('sip:666@{}:{}'.format(
            *REMOTE_ADDR)))

    async def reader():
        async for request in subscription:
            print('NOTIFY:', request.payload)
            await subscription.reply(request, status_code=200)

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(reader(), timeout=duration)

    await subscription.close()


async def start(app, protocol, duration):
    if protocol is aiosip.WS:
        peer = await app.connect(
            'ws://{}:{}'.format(*REMOTE_ADDR),
            protocol=protocol,
            local_addr=LOCAL_ADDR)
    else:
        peer = await app.connect(
            REMOTE_ADDR, protocol=protocol, local_addr=LOCAL_ADDR)

    await run_subscription(peer, duration)
    await app.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    parser.add_argument('-d', '--duration', type=int, default=5)
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)

    if args.protocol == 'udp':
        loop.run_until_complete(start(app, aiosip.UDP, args.duration))
    elif args.protocol == 'tcp':
        loop.run_until_complete(start(app, aiosip.TCP, args.duration))
    elif args.protocol == 'ws':
        loop.run_until_complete(start(app, aiosip.WS, args.duration))
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
