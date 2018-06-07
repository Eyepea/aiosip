import argparse
import asyncio
import logging
import itertools

import aiosip


async def notify(dialog):
    for idx in itertools.count(1):
        print("------------>", idx)
        await dialog.notify(payload=str(idx))
        await asyncio.sleep(1)


async def on_subscribe(request):
    expires = int(request.message.headers['Expires'])
    dialog = await request.accept(headers={'Expires': expires})

    if not expires:
        return

    print('Subscription started!')
    task = asyncio.ensure_future(notify(dialog))

    async for transaction in dialog:
        expires = int(transaction.message.headers['Expires'])
        await transaction.accept(headers={'Expires': expires})

        if expires == 0:
            break

    task.cancel()
    print('Subscription ended!')


class Dialplan(aiosip.BaseDialplan):
    async def resolve(self, *args, **kwargs):
        await super().resolve(*args, **kwargs)

        if kwargs['method'] == 'SUBSCRIBE':
            return on_subscribe


def start(app, protocol):
    app.loop.run_until_complete(
        app.run(
            protocol=protocol,
            local_addr=('127.0.0.1', 5060)))

    print('Serving on {} {}'.format(('127.0.0.1', 5060), protocol))

    try:
        app.loop.run_forever()
    except KeyboardInterrupt:
        pass

    print('Closing')
    app.loop.run_until_complete(app.close())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop, dialplan=Dialplan())

    if args.protocol == 'udp':
        start(app, aiosip.UDP)
    elif args.protocol == 'tcp':
        start(app, aiosip.TCP)
    elif args.protocol == 'ws':
        start(app, aiosip.WS)
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
