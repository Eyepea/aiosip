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
def handle_subscribe(dialog, message):
    for idx in range(1, 11):
        yield from dialog.send_message('NOTIFY',
                                       to_details=message.to_details,
                                       from_details=message.from_details,
                                       headers={'Via': message.headers['Via'],
                                                'Call-ID': message.headers['Call-ID']},
                                       payload=str(idx))
        yield from asyncio.sleep(1)


@asyncio.coroutine
def start_subscription(dialog, message):
    assert message.method == 'REGISTER'

    dialog.register_callback('SUBSCRIBE', handle_subscribe)

    dialog.send_reply(status_code=200,
                      status_message='OK',
                      to_details=message.to_details,
                      from_details=message.from_details,
                      headers={'Via': message.headers['Via'],
                               'CSeq': message.headers['CSeq'],
                               'Call-ID': message.headers['Call-ID']})

    print('Subscription started!')


def main_tcp(app):
    server = app.loop.run_until_complete(
        app.create_connection(
            protocol=aiosip.TCP,
            mode=aiosip.SERVER,
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
    protocol = app.loop.run_until_complete(
        app.create_connection(
            local_addr=(sip_config['local_ip'], sip_config['local_port'])
        )
    )

    print('Serving on {} UDP'.format((sip_config['local_ip'], sip_config['local_port'])))

    try:
        app.loop.run_forever()
    except KeyboardInterrupt:
        pass

    print('Closing')


def main():
    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('subscriber', start_subscription)

    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        main_tcp(app)
    else:
        main_udp(app)

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
