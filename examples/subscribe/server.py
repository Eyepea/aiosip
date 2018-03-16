import argparse
import asyncio
import logging
import itertools

import aiosip

sip_config = {
    'srv_host': 'xxxxxx',
    'srv_port': '7000',
    'realm': 'XXXXXX',
    'user': 'YYYYYY',
    'pwd': 'ZZZZZZ',
    'local_ip': '127.0.0.1',
    'local_port': 6000
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
        if expires == 0:
            break

    task.cancel()
    print('Subscription ended!')


def start(app, protocol):
    app.loop.run_until_complete(
        app.run(
            protocol=protocol,
            local_addr=(sip_config['local_ip'], sip_config['local_port'])))

    print('Serving on {} {}'.format(
        (sip_config['local_ip'], sip_config['local_port']), protocol))

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
    app.dialplan.add_user('subscriber', {
        'SUBSCRIBE': on_subscribe
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
