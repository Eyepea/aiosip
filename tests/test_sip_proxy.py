import aiosip
import pytest
import asyncio
import itertools


@pytest.mark.parametrize('close_order', itertools.permutations(('client', 'server', 'proxy')))  # noQa C901: too complex
async def test_proxy_subscribe(test_server, test_proxy, protocol, loop, from_details, to_details, close_order):
    callback_complete = loop.create_future()
    callback_complete_proxy = loop.create_future()

    class ServerDialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.subscribe

        async def subscribe(self, request, message):
            await request.prepare(status_code=200)
            callback_complete.set_result(message)

    class ProxyDialplan(aiosip.BaseDialplan):
        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)

            return self.proxy_subscribe

        async def proxy_subscribe(self, request, message):
            dialog = await request.proxy(message)
            callback_complete_proxy.set_result(message)
            async for message in dialog:
                dialog.proxy(message)

    app = aiosip.Application(loop=loop, debug=True)

    server_app = aiosip.Application(loop=loop, debug=True, dialplan=ServerDialplan())
    await test_server(server_app)

    proxy_app = aiosip.Application(loop=loop, dialplan=ProxyDialplan())
    proxy = await test_proxy(proxy_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(proxy.sip_config['server_host'], proxy.sip_config['server_port'])
    )

    await peer.subscribe(
        expires=1800,
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    received_request_server = await asyncio.wait_for(callback_complete, timeout=2)
    received_request_proxy = await asyncio.wait_for(callback_complete_proxy, timeout=2)

    assert received_request_server.method == 'SUBSCRIBE'
    assert received_request_server.payload == received_request_proxy.payload
    assert received_request_server.headers == received_request_proxy.headers

    for item in close_order:
        if item == 'client':
            await app.close()
        elif item == 'server':
            await server_app.close()
        elif item == 'proxy':
            await proxy_app.close()
        else:
            raise ValueError('Invalid close_order')


@pytest.mark.parametrize('close_order', itertools.permutations(('client', 'server', 'proxy')))  # noQa C901: too complex
async def test_proxy_notify(test_server, test_proxy, protocol, loop, from_details, to_details, close_order):

    callback_complete = loop.create_future()
    callback_complete_proxy = loop.create_future()

    class ServerDialpan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)

            return self.subscribe

        async def subscribe(self, request, message):
            dialog = await request.prepare(status_code=200)
            await asyncio.sleep(0.2)
            await dialog.notify(payload='1')

    class ProxyDialplan(aiosip.BaseDialplan):
        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)

            return self.proxy_subscribe

        async def proxy_subscribe(self, request, message):
            dialog = await request.proxy(message)

            async for message in dialog:
                dialog.proxy(message)

                if message.method == 'NOTIFY':
                    callback_complete_proxy.set_result(message)

    app = aiosip.Application(loop=loop, debug=True)

    server_app = aiosip.Application(loop=loop, debug=True, dialplan=ServerDialpan())
    await test_server(server_app)

    proxy_app = aiosip.Application(loop=loop, debug=True, dialplan=ProxyDialplan())
    proxy = await test_proxy(proxy_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(proxy.sip_config['server_host'], proxy.sip_config['server_port'])
    )

    subscription = await peer.subscribe(
        expires=1800,
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details)
    )

    async for msg in subscription:
        await subscription.reply(msg, 200)
        callback_complete.set_result(msg)
        break  # We only expect a single message

    received_notify_server = await asyncio.wait_for(callback_complete, timeout=2)
    received_notify_proxy = await asyncio.wait_for(callback_complete_proxy, timeout=2)

    assert received_notify_server.method == 'NOTIFY'
    assert received_notify_server.payload == '1'

    assert received_notify_server.payload == received_notify_proxy.payload
    assert received_notify_server.headers == received_notify_proxy.headers

    for item in close_order:
        if item == 'client':
            await app.close()
        elif item == 'server':
            await server_app.close()
        elif item == 'proxy':
            await proxy_app.close()
        else:
            raise ValueError('Invalid close_order')
