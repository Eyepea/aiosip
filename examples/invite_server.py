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


async def notify(dialog):
    for idx in range(1, 4):
        await dialog.notify(payload=str(idx))
        await asyncio.sleep(1)


async def on_bye(dialog, message):
    await dialog.reply(message, status_code=200)
    print('Hangup successful')


async def on_invite(dialog, message):
    print('Call ringing!')
    await dialog.reply(message, status_code=100)
    await dialog.reply(message, status_code=180)

    await asyncio.sleep(3)
    await dialog.reply(message, status_code=200)
    print('Call started!')


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


def main_ws(app):
    server = app.loop.run_until_complete(
        app.run(
            protocol=aiosip.WS,
            local_addr=(sip_config['local_ip'], sip_config['local_port'])
        )
    )

    print('Serving WS')

    try:
        app.loop.run_forever()
    except KeyboardInterrupt:
        pass

    print('Closing')
    server.close()
    app.loop.run_until_complete(server.wait_closed())


def main():
    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('aiosip', {'INVITE': on_invite,
                                     'BYE': on_bye})

    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        main_tcp(app)
    elif len(sys.argv) > 1 and sys.argv[1] == 'ws':
        main_ws(app)
    else:
        main_udp(app)

    # loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
