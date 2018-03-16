import argparse
import asyncio
import contextlib
import logging
import random

import aiosip

from util import Registration

sip_config = {
    'srv_host': '127.0.0.1',
    'srv_port': 6000,
    'realm': 'XXXXXX',
    'user': None,
    'pwd': 'hunter2',
    'local_host': '127.0.0.1',
    'local_port': random.randint(6001, 6100)
}


async def run_subscription(peer, user, duration):
    subscription = await peer.subscribe(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        to_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            user, sip_config['srv_host'], sip_config['srv_port'])),
        password=sip_config['pwd'])

    if subscription.status_code == 404:
        print("Subscription not found, did you forget to register it?")
        return
    elif subscription.status_code != 200:
        print("Subscription failed, got {}".format(subscription.status_code))
        return

    async def reader():
        async for request in subscription:
            print('NOTIFY:', request.payload)
            await subscription.reply(request, status_code=200)

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(reader(), timeout=duration)

    # TODO: needs a better API
    await subscription._subscribe(expires=0)


async def start(app, protocol, target, duration):
    if protocol is aiosip.WS:
        peer = await app.connect(
            'ws://{}:{}'.format(sip_config['srv_host'], sip_config['srv_port']),
            protocol=protocol,
            local_addr=(sip_config['local_host'], sip_config['local_port']))
    else:
        peer = await app.connect(
            (sip_config['srv_host'], sip_config['srv_port']),
            protocol=protocol,
            local_addr=(sip_config['local_host'], sip_config['local_port']))

    registration = Registration(
        peer=peer,
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        to_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['srv_host'],
            sip_config['srv_port'])),
        contact_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        password=sip_config['pwd']
    )

    async with registration:
        await run_subscription(peer, target, duration)

    await app.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    parser.add_argument('-u', '--user', default='client')
    parser.add_argument('-d', '--duration', type=int, default=5)
    parser.add_argument('target')
    args = parser.parse_args()

    sip_config['user'] = args.user

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)

    if args.protocol == 'udp':
        client = start(app, aiosip.UDP, args.target, args.duration)
    elif args.protocol == 'tcp':
        client = start(app, aiosip.TCP, args.target, args.duration)
    elif args.protocol == 'ws':
        client = start(app, aiosip.WS, args.target, args.duration)
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    loop.run_until_complete(client)
    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
