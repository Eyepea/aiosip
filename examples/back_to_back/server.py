import argparse
import asyncio
import itertools
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


async def notify(dialog):
    for idx in itertools.count(1):
        await dialog.notify(payload=str(idx))
        await asyncio.sleep(1)


async def on_subscribe(request, message):
    expires = int(message.headers['Expires'])
    dialog = await request.prepare(status_code=200,
                                   headers={'Expires': expires})

    if not expires:
        return

    print('Subscription started!')
    task = asyncio.ensure_future(notify(dialog))
    async for message in dialog:
        expires = int(message.headers['Expires'])

        await dialog.reply(message, 200, headers={'Expires': expires})
        if not expires:
            break

    task.cancel()
    print('Subscription ended!')



class Dialplan(aiosip.BaseDialplan):

    async def resolve(self, *args, **kwargs):
        await super().resolve(*args, **kwargs)

        if kwargs['message'].method == 'SUBSCRIBE':
            return on_subscribe()


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

    return Registration(
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    parser.add_argument('user')
    args = parser.parse_args()

    sip_config['user'] = args.user

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop, dialplan=Dialplan())

    if args.protocol == 'udp':
        server = start(app, aiosip.UDP)
    elif args.protocol == 'tcp':
        server = start(app, aiosip.TCP)
    elif args.protocol == 'ws':
        server = start(app, aiosip.WS)
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    # TODO: refactor
    registration = loop.run_until_complete(server)
    loop.run_until_complete(registration.__aenter__())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.run_until_complete(registration.__aexit__(None, None, None))

    print('Closing')
    loop.run_until_complete(app.close())
    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
