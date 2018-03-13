import argparse
import asyncio
import logging
import random

import aiosip
from aiosip.contrib import session

sip_config = {
    'srv_host': '127.0.0.1',
    'srv_port': 6000,
    'realm': 'XXXXXX',
    'user': None,
    'pwd': 'hunter2',
    'local_host': '127.0.0.1',
    'local_port': random.randint(6001, 6100)
}


async def notify(dialog):
    for idx in range(1, 4):
        await dialog.notify(payload=str(idx))
        await asyncio.sleep(1)


async def on_subscribe(dialog, message):
    try:
        print('Subscription started!')
        await notify(dialog)
    except asyncio.CancelledError:
        pass

    print('Subscription ended!')


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


async def start(app, protocol):
    await app.run(
        protocol=protocol,
        local_addr=(sip_config['local_host'], sip_config['local_port']))

    print('Serving on {} {}'.format(
        (sip_config['local_host'], sip_config['local_port']), protocol))

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    parser.add_argument('user')
    args = parser.parse_args()

    sip_config['user'] = args.user

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user(args.user, {
        'SUBSCRIBE': session(on_subscribe)
    })

    if args.protocol == 'udp':
        server = start(app, aiosip.UDP)
    elif args.protocol == 'tcp':
        server = start(app, aiosip.TCP)
    elif args.protocol == 'ws':
        server = start(app, aiosip.WS)
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    try:
        loop.run_until_complete(server)
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    print('Closing')
    loop.run_until_complete(app.close())
    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
