import time
import aiosip
import asyncio
import logging
import async_timeout

FROM = 'sip:qd.{username}@qd.allocloud.com:16000'
TO = 'sip:qd.{username}@qd.allocloud.com:16000'

SDP_INVITE = """v=0
o=- 20000 20000 IN IP4 192.168.8.178
s=SDP data
c=IN IP4 192.168.8.178
t=0 0
m=audio 12350 RTP/AVP 8 101
a=rtpmap:8 PCMA/8000
a=ptime:20
a=sendrecv
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-15"""

SDP_OK = """v=0
o=- 20000 20000 IN IP4 192.168.8.178
s=SDP data
c=IN IP4 192.168.8.178
t=0 0
m=audio 12040 RTP/AVP 8 101
a=rtpmap:8 PCMA/8000
a=ptime:20
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-15
a=sendrecv"""


async def main():

    await asyncio.gather(
        peer1(username='w9g1pizf', password='WNbqOWR0GeqEWPHLbUw'),
        peer2(username='5kztmikz', password='5zv02H8X3VbR5po6gW8'),
    )


async def peer1(username, password):
    async with aiosip.client.Peer(
        host='217.182.114.36',
        port=10060,
        protocol=aiosip.UDP
    ) as peer:

        peer.add_route('options', options)
        peer.add_route('notify', notify)

        async with peer.register(
            from_details=aiosip.Contact.from_header(FROM.format(username=username)),
            to_details=aiosip.Contact.from_header(TO.format(username=username)),
            password=password,
            expires=10
        ):

            await asyncio.sleep(1)

            start, end = None, None
            async for message in peer.invite(
                from_details=aiosip.Contact.from_header(FROM.format(username=username)),
                to_details=aiosip.Contact.from_header('sip:461@qd.allocloud.com:16000'),
                password=password,
                sdp=SDP_INVITE
            ):
                if isinstance(message, aiosip.Response) and message.status_code == 200:
                    start = time.time()
                elif isinstance(message, aiosip.Request) and message.method == 'BYE':
                    end = time.time()

            if start and end:
                print(f'Call time: {int(end) - int(start)} seconds')


async def peer2(username, password):
    async with aiosip.client.Peer(
        host='217.182.114.36',
        port=10060,
        protocol=aiosip.UDP
    ) as peer:

        peer['call_completed'] = asyncio.Future()

        peer.add_route('options', options)
        peer.add_route('notify', notify)
        peer.add_route('invite', invite)

        async with peer.register(
            from_details=aiosip.Contact.from_header(FROM.format(username=username)),
            to_details=aiosip.Contact.from_header(TO.format(username=username)),
            password=password,
            expires=10
        ):

            await peer['call_completed']


async def invite(dialog):
    await dialog.reply(dialog.original_msg, status_code=100)
    await asyncio.sleep(0.5)
    await dialog.reply(dialog.original_msg, status_code=180)
    await asyncio.sleep(2)
    await dialog.reply(dialog.original_msg, status_code=200, payload=SDP_OK, headers={"Content-Type": "application/sdp"})

    try:
        async with async_timeout.timeout(5):
            async for msg in dialog:
                if msg.method in ('CANCEL', 'BYE'):
                    await dialog.reply(msg, status_code=200)
                    break
    except asyncio.TimeoutError:
        await dialog.request('BYE')
        await dialog.close()
        dialog.peer['call_completed'].set_result(True)


async def options(dialog):
    # print(dialog.original_msg)
    await dialog.reply(dialog.original_msg, status_code=200)


async def notify(dialog):
    # print(dialog.original_msg)
    await dialog.reply(dialog.original_msg, status_code=200)


if __name__ == '__main__':
    asyncio.run(main())
    logging.basicConfig(level=logging.DEBUG)
