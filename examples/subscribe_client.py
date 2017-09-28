import asyncio
import logging
import random
import sys

import aiosip

sip_config = {
    'srv_host': '127.0.0.1',
    'srv_port': 6000,
    'realm': 'XXXXXX',
    'user': 'subscriber',
    'pwd': 'hunter2',
    'local_ip': '127.0.0.1',
    'local_port': random.randint(6001, 6100)
}


@asyncio.coroutine
def show_notify(dialog, message):
    print('NOTIFY:', message.payload)


@asyncio.coroutine
def option(dialog, request):

    response = aiosip.Response.from_request(
        request=request,
        status_code=200,
        status_message='OK'
    )
    dialog.reply(response)


@asyncio.coroutine
def start(app, protocol):

    connection = yield from app.connect((sip_config['local_ip'], sip_config['local_port']),
                                        (sip_config['srv_host'], sip_config['srv_port']),
                                        protocol)

    register_dialog = connection.create_dialog(
        from_uri='sip:{}@{}:{}'.format(sip_config['user'], sip_config['local_ip'], sip_config['local_port']),
        to_uri='sip:{}@{}:{}'.format(sip_config['user'], sip_config['srv_host'], sip_config['srv_port']),
        password=sip_config['pwd'],
    )
    yield from register_dialog.register()
    register_dialog.close()

    subscribe_dialog = connection.create_dialog(
        from_uri='sip:{}@{}:{}'.format(sip_config['user'], sip_config['local_ip'], sip_config['local_port']),
        to_uri='sip:666@{}:{}'.format(sip_config['srv_host'], sip_config['srv_port']),
        password=sip_config['pwd']
    )
    subscribe_dialog.register_callback('NOTIFY', show_notify)
    yield from subscribe_dialog.send(
        method='SUBSCRIBE',
        headers={'Expires': '1800',
                 'Event': 'dialog',
                 'Accept': 'application/dialog-info+xml'}
    )

    yield from asyncio.sleep(20)
    subscribe_dialog.close()


def main():
    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('asterisk', option)

    if len(sys.argv) > 1 and sys.argv[1] == 'tcp':
        loop.run_until_complete(start(app, aiosip.TCP))
    else:
        loop.run_until_complete(start(app, aiosip.UDP))

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
