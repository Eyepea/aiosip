import logging
import asyncio
from aiohttp import multidict

import aiosip



sip_config = {  'srv_host' : 'XXXXXXX',
                 'srv_port'  : '5060',
                 'realm' : 'XXXXXX',
                 'user'  : 'YYYYYY',
                 'pwd'   : 'ZZZZZZ',
                 'local_ip' : '0.0.0.0',
                 'local_port': None
             }


def show_notify(dialog, message):
    print(message)



@asyncio.coroutine
def main(loop):
    app = aiosip.Application(loop=loop)

    dialog = yield from app.start_dialog(from_uri='sip:{user}@{realm}:{srv_port}'.format(**sip_config),
                                         to_uri='sip:{user}@{realm}:{srv_port}'.format(**sip_config),
                                         local_addr=(sip_config['local_ip'], sip_config['local_port']),
                                         remote_addr=(sip_config['srv_host'], sip_config['srv_port']),
                                         password=sip_config['pwd'],
                                         )

    fut = dialog.register()
    try:
        result = yield from asyncio.wait_for(fut, 5, loop=loop)
        print('register ok')
    except asyncio.TimeoutError:
        print('Timeout doing REGISTER !')


    dialog.register_callback('NOTIFY', show_notify)

    watched_user = '666'

    headers = multidict.CIMultiDict()
    headers['Expires'] = '1800'
    headers['Event'] = 'dialog'
    headers['Accept'] = 'application/dialog-info+xml'

    send_future = dialog.send_message(method='SUBSCRIBE',
                                      to_uri='sip:{0}@{realm}:{srv_port}'.format(watched_user, **sip_config),
                                      headers=headers,
                                      payload='')

    try:
        result = yield from asyncio.wait_for(send_future, 5, loop=loop)
        print('%s: %s' % (result.status_code, result.status_message))
    except asyncio.TimeoutError:
        print('Message not received !')
    yield from asyncio.sleep(240)  # wait NOTIFY messages

    dialog.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(loop))
