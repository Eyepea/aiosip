import argparse
import asyncio
import contextlib
import logging
import random

import aiosip

sip_config = {
    'srv_host': '127.0.0.1',
    'srv_port': 6000,
    'realm': 'XXXXXX',
    'user': 'aiosip',
    'pwd': 'hunter2',
    'local_host': '127.0.0.1',
    'local_port': random.randint(6001, 6100)
}


async def run_call(peer, duration):
    call = await peer.invite(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(
            sip_config['user'], sip_config['local_host'],
            sip_config['local_port'])),
        to_details=aiosip.Contact.from_header('sip:666@{}:{}'.format(
            sip_config['srv_host'], sip_config['srv_port'])),
        password=sip_config['pwd'])

    async with call:
        async def reader():
            async for msg in call.wait_for_terminate():
                print("CALL STATUS:", msg.status_code)

            print("CALL ESTABLISHED")
            await asyncio.sleep(5)
            print("GOING AWAY...")

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(reader(), timeout=duration)

    print("CALL TERMINATED")


async def start(app, protocol, duration):
    if protocol is aiosip.WS:
        peer = await app.connect(
            'ws://{}:{}'.format(sip_config['srv_host'], sip_config['srv_port']),
            protocol=protocol,
            local_addr=(sip_config['local_host'], sip_config['local_port']))
    else:
        peer = await app.connect(
            (sip_config['srv_host'], sip_config['srv_port']),
            protocol=protocol,
            local_addr=(sip_config['local_host'], sip_config['local_port']))

    await run_call(peer, duration)
    await app.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--protocol', default='udp')
    parser.add_argument('-d', '--duration', type=int, default=5)
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    app = aiosip.Application(loop=loop)

    if args.protocol == 'udp':
        loop.run_until_complete(start(app, aiosip.UDP, args.duration))
    elif args.protocol == 'tcp':
        loop.run_until_complete(start(app, aiosip.TCP, args.duration))
    elif args.protocol == 'ws':
        loop.run_until_complete(start(app, aiosip.WS, args.duration))
    else:
        raise RuntimeError("Unsupported protocol: {}".format(args.protocol))

    loop.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
