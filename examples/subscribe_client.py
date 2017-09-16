import logging
import asyncio

import aiosip


def show_notify(dialog, message):
    print(message)


@asyncio.coroutine
def main(loop):
    app = aiosip.Application(loop=loop)

    dialog = yield from app.start_dialog(
        aiosip.Dialog,
        from_uri='sip:subscriber@localhost:5080',
        to_uri='sip:server@localhost:5060',
        password='hunter2',
    )

    fut = dialog.register()
    try:
        result = yield from asyncio.wait_for(fut, 5, loop=loop)
        print('Register OK')
    except asyncio.TimeoutError:
        print('Timeout doing REGISTER!')

    dialog.register_callback('NOTIFY', show_notify)

    headers = {
        'Expires': '1800',
        'Event': 'dialog',
        'Accept': 'application/dialog-info+xml'
    }

    send_future = dialog.send_message(
        method='SUBSCRIBE',
        to_details=aiosip.Contact.from_header('sip:666@localhost:5060'),
        headers=headers,
    )

    try:
        result = yield from asyncio.wait_for(send_future, 5, loop=loop)
        print('%s: %s' % (result.status_code, result.status_message))
    except asyncio.TimeoutError:
        print('Message not received!')

    dialog.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(loop))
