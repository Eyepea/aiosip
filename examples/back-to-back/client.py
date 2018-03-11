import argparse
import asyncio
import logging
import random

import aiosip

sip_config = {
    'srv_host': '127.0.0.1',
    'srv_port': 6000,
    'realm': 'XXXXXX',
    'user': None,
    'pwd': 'hunter2',
    'local_host': '127.0.0.1',
    'local_port': random.randint(6001, 6100)
}


async def run_registration(peer):
    await peer.register(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        to_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['srv_host'],
            sip_config['srv_port'])),
        contact_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        password=sip_config['pwd'])


async def run_subscription(peer, user):
    subscription = await peer.subscribe(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        to_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            user, sip_config['srv_host'], sip_config['srv_port'])),
        password=sip_config['pwd'])

    if subscription.status_code == 404:
        print("Subscription not found, did you forget to register it?")
    elif subscription.status_code != 200:
        print("Subscription failed, got {}".format(subscription.status_code))
    else:
        async for request in subscription:
            print('NOTIFY:', request.payload)
            await subscription.reply(request, status_code=200)


async def start(app, protocol, target):
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

    await run_registration(peer)
    await run_subscription(peer, target)
    await app.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    parser.add_argument('-u', '--user', default='client')
    parser.add_argument('target')
    args = parser.parse_args()

    sip_config['user'] = args.user

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)

    if args.protocol == 'udp':
        client = start(app, aiosip.UDP, args.target)
    elif args.protocol == 'tcp':
        client = start(app, aiosip.TCP, args.target)
    elif args.protocol == 'ws':
        client = start(app, aiosip.WS, args.target)
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    loop.run_until_complete(client)
    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
