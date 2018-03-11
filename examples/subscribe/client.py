import asyncio
import contextlib
import logging
import random
import sys

import aiosip

sip_config = {
    'srv_host': '127.0.0.1',
    'srv_port': 6000,
    'realm': 'XXXXXX',
    'user': 'subscriber',
    'pwd': 'hunter2',
    'local_host': '127.0.0.1',
    'local_port': random.randint(6001, 6100)
}


async def option(dialog, request):
    await dialog.reply(request, status_code=200)


async def run_subscription(peer):
    subscription = await peer.subscribe(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        to_details=aiosip.Contact.from_header('sip:666@{}:{}'.format(
            sip_config['srv_host'], sip_config['srv_port'])),
        password=sip_config['pwd'])

    async for request in subscription:
        print('NOTIFY:', request.payload)
        await subscription.reply(request, status_code=200)


async def start(app, protocol):
    if protocol is aiosip.WS:
        peer = await app.connect('ws://{}:{}'.format(
            sip_config['srv_host'], sip_config['srv_port']), protocol)
    else:
        peer = await app.connect(
            (sip_config['srv_host'], sip_config['srv_port']), protocol)

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(run_subscription(peer), timeout=5)
    await app.close()


def main():
    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('asterisk', option)

    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        loop.run_until_complete(start(app, aiosip.TCP))
    elif len(sys.argv) > 1 and sys.argv[1] == 'ws':
        loop.run_until_complete(start(app, aiosip.WS))
    else:
        loop.run_until_complete(start(app, aiosip.UDP))

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
