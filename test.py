import aiosip
import asyncio
import logging


async def register():

    async with aiosip.client.Peer(
        host='',
        port=0,
       protocol=aiosip.UDP
    ) as peer:

        dialog = await peer.register(
            from_details=aiosip.Contact.from_header(''),
            to_details=aiosip.Contact.from_header(''),
            password='',
        )

        await asyncio.sleep(120)


async def main():
    await asyncio.gather(
        register(),
    )


if __name__ == '__main__':
    asyncio.run(main())
    logging.basicConfig(level=logging.DEBUG)
