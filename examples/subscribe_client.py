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


async def show_notify(dialog, request):
    print('NOTIFY:', request.payload)
    await dialog.reply(request, status_code=200)


async def option(dialog, request):
    await dialog.reply(request, status_code=200)


async def start(app, protocol):

    peer = await app.connect((sip_config['srv_host'], sip_config['srv_port']), protocol)

    register_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(
            'sip:{}@{}:{}'.format(sip_config['user'], sip_config['local_ip'], sip_config['local_port'])),
        to_details=aiosip.Contact.from_header(
            'sip:{}@{}:{}'.format(sip_config['user'], sip_config['srv_host'], sip_config['srv_port'])),
        password=sip_config['pwd'],
    )

    await register_dialog.register()

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(
            'sip:{}@{}:{}'.format(sip_config['user'], sip_config['local_ip'], sip_config['local_port'])),
        to_details=aiosip.Contact.from_header(
            'sip:666@{}:{}'.format(sip_config['srv_host'], sip_config['srv_port'])),
        password=sip_config['pwd']
    )

    subscribe_dialog.router['notify'] = show_notify
    await subscribe_dialog.subscribe()
    await asyncio.sleep(20)
    await subscribe_dialog.subscribe(expires=0)


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
