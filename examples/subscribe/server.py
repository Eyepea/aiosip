import asyncio
import logging
import sys

import aiosip
from aiosip.contrib import session

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
    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('subscriber', {
        'SUBSCRIBE': session(on_subscribe)
    })

    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        start(app, aiosip.TCP)
    elif len(sys.argv) > 1 and sys.argv[1] == 'ws':
        start(app, aiosip.WS)
    else:
        start(app, aiosip.UDP)

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
