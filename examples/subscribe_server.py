import asyncio
import logging
import sys

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


@asyncio.coroutine
def notify(dialog):
    for idx in range(1, 4):
        yield from dialog.request('NOTIFY',
                                  payload=str(idx))
        yield from asyncio.sleep(1)


@asyncio.coroutine
def on_register(dialog, message):
    dialog.reply(message, status_code=200)
    print('Registration successful')


@asyncio.coroutine
def on_subscribe(dialog, message):
    dialog.reply(message, status_code=200)
    print('Subscription started!')
    yield from notify(dialog)


def main_tcp(app):
    server = app.loop.run_until_complete(
        app.run(
            protocol=aiosip.TCP,
            local_addr=(sip_config['local_ip'], sip_config['local_port'])
        )
    )

    print('Serving on {} TCP'.format(server.sockets[0].getsockname()))

    try:
        app.loop.run_forever()
    except KeyboardInterrupt:
        pass

    print('Closing')
    server.close()
    app.loop.run_until_complete(server.wait_closed())


def main_udp(app):
    app.loop.run_until_complete(app.run(local_addr=(sip_config['local_ip'], sip_config['local_port'])))

    print('Serving on {} UDP'.format((sip_config['local_ip'], sip_config['local_port'])))

    try:
        app.loop.run_forever()
    except KeyboardInterrupt:
        pass

    print('Closing')


def main():
    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('subscriber', {'REGISTER': on_register,
                                         'SUBSCRIBE': on_subscribe})

    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        main_tcp(app)
    else:
        main_udp(app)

    # loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
