import asyncio
import aiosip


async def test_proxy_subscribe(test_server, test_proxy, protocol, loop, from_details, to_details):
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
            dialog = request._create_dialog()
            peer = await aiosip.utils.get_proxy_peer(dialog, message)

            async for proxy_response in peer.proxy_request(dialog, message, 0.1):
                if proxy_response:
                    dialog.peer.proxy_response(proxy_response)

            callback_complete_proxy.set_result(message)

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

    await server_app.close()
    await proxy_app.close()
    await app.close()


async def test_proxy_notify(test_server, test_proxy, protocol, loop, from_details, to_details):
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
            dialog = request._create_dialog()
            peer = await aiosip.utils.get_proxy_peer(dialog, message)

            async for proxy_response in peer.proxy_request(dialog, message, 0.1):
                if proxy_response:
                    dialog.peer.proxy_response(proxy_response)

            # TODO: refactor
            subscription = request.app._dialogs[frozenset((
                message.to_details.details,
                message.from_details.details,
                message.headers['Call-ID']
            ))]

            async for msg in subscription:
                async for proxy_response in dialog.peer.proxy_request(subscription, msg):
                    if proxy_response:
                        peer.proxy_response(proxy_response)
                callback_complete_proxy.set_result(msg)

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

    await server_app.close()
    await proxy_app.close()
    await app.close()
