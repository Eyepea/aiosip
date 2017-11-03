import asyncio
import aiosip


async def test_proxy_subscribe(test_server, test_proxy, protocol, loop, from_details, to_details):
    callback_complete = loop.create_future()
    callback_complete_proxy = loop.create_future()

    async def subscribe(dialog, request):
        await dialog.reply(request, status_code=200)
        callback_complete.set_result(request)

    async def proxy_subscribe(dialog, request):
        callback_complete_proxy.set_result(request)
        await dialog.router.proxy(dialog, request)

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': subscribe})
    await test_server(server_app)

    proxy_router = aiosip.ProxyRouter()
    proxy_router['subscribe'] = proxy_subscribe
    proxy_app = aiosip.Application(loop=loop)
    proxy_app.dialplan.add_user('pytest', proxy_router)
    proxy = await test_proxy(proxy_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(proxy.sip_config['server_host'], proxy.sip_config['server_port'])
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    response = await subscribe_dialog.subscribe(expires=1800)

    received_request_server = await callback_complete
    received_request_proxy = await callback_complete_proxy

    assert response.status_code == 200
    assert response.status_message == 'OK'
    assert received_request_server.method == 'SUBSCRIBE'
    assert received_request_server.payload == received_request_proxy.payload
    assert received_request_server.headers == received_request_proxy.headers

    server_app.close()
    proxy_app.close()


async def test_proxy_notify(test_server, test_proxy, protocol, loop, from_details, to_details):
    callback_complete = loop.create_future()
    callback_complete_proxy = loop.create_future()

    async def subscribe(dialog, request):
        assert len(dialog.peer.subscriber) == 1
        await dialog.reply(request, status_code=200)
        await asyncio.sleep(0.2)
        await dialog.notify(payload='1')

    async def notify(dialog, request):
        await dialog.reply(request, 200)
        callback_complete.set_result(request)

    async def proxy_notify(dialog, request):
        await dialog.router.proxy(dialog, request)
        callback_complete_proxy.set_result(request)

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': subscribe})
    await test_server(server_app)

    proxy_router = aiosip.ProxyRouter()
    proxy_router['notify'] = proxy_notify
    proxy_app = aiosip.Application(loop=loop)
    proxy_app.dialplan.add_user('pytest', proxy_router)
    proxy = await test_proxy(proxy_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(proxy.sip_config['server_host'], proxy.sip_config['server_port'])
    )

    client_router = aiosip.Router()
    client_router['notify'] = notify

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
        router=client_router
    )

    response = await subscribe_dialog.subscribe(expires=1800)

    received_notify_server = await callback_complete
    received_notify_proxy = await callback_complete_proxy

    assert response.status_code == 200
    assert response.status_message == 'OK'

    assert received_notify_server.method == 'NOTIFY'
    assert received_notify_server.payload == '1'

    assert received_notify_server.payload == received_notify_proxy.payload
    assert received_notify_server.headers == received_notify_proxy.headers

    server_app.close()
    proxy_app.close()
