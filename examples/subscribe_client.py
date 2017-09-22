import asyncio
import logging
import random
import sys

import aiosip

sip_config = {
    'srv_host': '127.0.0.1',
    'srv_port': 6000,
    'realm': 'XXXXXX',
    'user': 'YYYYYY',
    'pwd': 'ZZZZZZ',
    'local_ip': '127.0.0.1',
    'local_port': random.randint(6001, 6100)
}


@asyncio.coroutine
def show_notify(dialog, message):
    print('NOTIFY:', message.payload)


@asyncio.coroutine
def start(app, protocol):
    dialog = yield from app.start_dialog(
        protocol=protocol,
        from_uri='sip:subscriber@localhost:{}'.format(sip_config['local_port']),
        to_uri='sip:server@localhost:{}'.format(sip_config['srv_port']),
        password='hunter2',
    )
    dialog.register_callback('NOTIFY', show_notify)

    yield from dialog.register()

    yield from dialog.send_message(
        method='SUBSCRIBE',
        to_details=aiosip.Contact.from_header('sip:666@localhost:5060'),
        headers={'Expires': '1800',
                 'Event': 'dialog',
                 'Accept': 'application/dialog-info+xml'}
    )

    yield from asyncio.sleep(20)
    dialog.close()


def main():
    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)

    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        loop.run_until_complete(start(app, aiosip.TCP))
    else:
        loop.run_until_complete(start(app, aiosip.UDP))

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
