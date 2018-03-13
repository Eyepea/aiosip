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


async def on_register(dialog, message):
    await dialog.reply(message, status_code=200)

    # TODO: multiple contact fields
    contact_uri = message.contact_details['uri']
    user = contact_uri['user']
    addr = contact_uri['host'], contact_uri['port']

    # TODO: unregistration
    locations[user].add(addr)
    print('Registration successful for {}'.format(user))


async def on_subscribe(dialog, message):
    to_uri = message.to_details['uri']
    user = to_uri['user']

    if user not in locations:
        # TODO: this needs to destory the dialog
        await dialog.reply(message, status_code=404)
        return

    await dialog.reply(message, status_code=200)

    for addr in locations[user]:
        peer = await dialog.app.connect(addr)

        subscription = await peer.subscribe(
            from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
                user, sip_config['local_host'], sip_config['local_port'])),
            to_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
                user, *addr)),
            password=sip_config['pwd'])

        assert subscription.status_code == 200
        async for request in subscription:
            await subscription.reply(request, status_code=200)

            print('FORWARDING:', request.payload)
            # TODO: need to sensibly forward headers
            await dialog.request(request.method, payload=request.payload)

        break  # Only looking for first entry for now


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
    app.dialplan.add_user('*', {
        'REGISTER': on_register,
        'SUBSCRIBE': on_subscribe,
    })

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
