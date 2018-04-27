import argparse
import asyncio
from collections import defaultdict
import logging

import aiosip

locations = defaultdict(set)
sip_config = {
    'srv_host': 'xxxxxx',
    'srv_port': '7000',
    'realm': 'XXXXXX',
    'user': 'YYYYYY',
    'pwd': 'ZZZZZZ',
    'local_host': '127.0.0.1',
    'local_port': 6000
}


async def on_register(request, message):
    expires = int(message.headers['Expires'])
    # TODO: challenge registrations
    dialog = await request.prepare(status_code=200)

    if not expires:
        return

    # TODO: multiple contact fields
    user = message.contact_details.user
    addr = message.contact_details.host, message.contact_details.port
    locations[user].add(addr)
    print('Registration established for {} at {}'.format(user, addr))

    async for message in dialog:
        expires = int(message.headers['Expires'])

        # TODO: challenge registrations
        await dialog.reply(message, 200)
        if not expires:
            break

    locations[user].remove(addr)
    print('Unregistering {} at {}'.format(user, addr))


async def on_subscribe(request, message):
    expires = int(message.headers['Expires'])
    user = message.to_details.user

    if user not in locations:
        # TODO: this needs to destory the dialog
        await request.prepare(status_code=404)
        return

    dialog = await request.prepare(status_code=200,
                                   headers={'Expires': expires})

    async def reader(peer):
        print('Forwarding subscription to {}'.format(peer))
        subscription = await peer.subscribe(
            from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
                user, sip_config['local_host'], sip_config['local_port'])),
            to_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
                user, *addr)),
            password=sip_config['pwd'],
            expires=expires)

        assert subscription.status_code == 200
        async for request in subscription:
            await subscription.reply(request, status_code=200)
            # TODO: need to sensibly forward headers
            await dialog.request(request.method, payload=request.payload)

    task = None
    for addr in locations[user]:
        peer = await dialog.app.connect(addr)
        task = asyncio.ensure_future(reader(peer))
        break  # Only looking for first entry for now

    print("Subscription forwarding started!")
    async for message in dialog:
        expires = int(message.headers['Expires'])

        await dialog.reply(message, 200, headers={'Expires': expires})
        if not expires:
            break

    task.cancel()
    print("Subscription forwarding ended!")


class Dialplan(aiosip.BaseDialplan):

    async def resolve(self, *args, **kwargs):
        await super().resolve(*args, **kwargs)

        if kwargs['method'] == 'SUBSCRIBE':
            return on_subscribe
        elif kwargs['method'] == 'REGISTER':
            return on_register


def start(app, protocol):
    app.loop.run_until_complete(
        app.run(
            protocol=protocol,
            local_addr=(sip_config['local_host'], sip_config['local_port'])))

    print('Serving on {} {}'.format(
        (sip_config['local_host'], sip_config['local_port']), protocol))

    try:
        app.loop.run_forever()
    except KeyboardInterrupt:
        pass

    print('Closing')
    app.loop.run_until_complete(app.close())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)

    if args.protocol == 'udp':
        start(app, aiosip.UDP)
    elif args.protocol == 'tcp':
        start(app, aiosip.TCP)
    elif args.protocol == 'ws':
        start(app, aiosip.WS)
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
