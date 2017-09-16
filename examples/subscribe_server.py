import logging
import asyncio

import aiosip


@asyncio.coroutine
def start_subscription(dialog, message):
    print('Subscription started!')

    headers = {
        'Via': message.headers['Via'],
        'CSeq': message.headers['CSeq'],
        'Call-ID': message.headers['Call-ID']
    }

    dialog.send_reply(status_code=200,
                      status_message='OK',
                      to_details=message.to_details,
                      from_details=message.from_details,
                      headers=headers)


@asyncio.coroutine
def main(loop):
    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('subscriber', start_subscription)

    server = yield from loop.create_datagram_endpoint(
        app.make_handler(aiosip.UDP),
        local_addr=('localhost', 5060)
    )

    return server


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(loop))
    loop.run_forever()
