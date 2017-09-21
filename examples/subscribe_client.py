import asyncio
import sys
import logging

import aiosip


@asyncio.coroutine
def main(port, loop):
    app = aiosip.Application(loop=loop)
    done = asyncio.Future(loop=loop)

    dialog = yield from app.start_dialog(
        aiosip.Dialog,
        from_uri='sip:subscriber@localhost:{}'.format(port),
        to_uri='sip:server@localhost:5060',
        password='hunter2',
    )

    fut = dialog.register()
    try:
        result = yield from asyncio.wait_for(fut, 5, loop=loop)
        print('Register OK')
    except asyncio.TimeoutError:
        print('Timeout doing REGISTER!')

    def show_notify(dialog, message):
        print('NOTIFY:', message.payload)
        if int(message.payload) == 10:
            done.set_result(None)

    dialog.register_callback('NOTIFY', show_notify)

    send_future = dialog.send_message(
        method='SUBSCRIBE',
        to_details=aiosip.Contact.from_header('sip:666@localhost:5060'),
        headers={'Expires': '1800',
                 'Event': 'dialog',
                 'Accept': 'application/dialog-info+xml'}
    )

    try:
        result = yield from asyncio.wait_for(send_future, 5, loop=loop)
        print('%s: %s' % (result.status_code, result.status_message))
    except asyncio.TimeoutError:
        print('Message not received!')

    yield from done
    dialog.close()


if __name__ == '__main__':
    try:
        port = int(sys.argv[1])
    except IndexError:
        port = 5080

    # logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(port, loop))
