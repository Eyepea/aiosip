import asyncio

import aiosip


@asyncio.coroutine
def test_subscribe(test_server, protocol, loop):
    callback_complete = loop.create_future()

    @asyncio.coroutine
    def handler(dialog, request):
        dialog.reply(request, status_code=200)
        callback_complete.set_result(request)

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': handler})
    server = yield from test_server(server_app)

    peer = yield from app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    from_details = 'sip:{user}@{host}:{port}'.format(
        user=server.sip_config['user'],
        host=server.sip_config['client_host'],
        port=server.sip_config['client_port']
    )
    to_details = 'sip:666@{host}:{port}'.format(
        host=server.sip_config['server_host'],
        port=server.sip_config['server_port']
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    response = yield from asyncio.wait_for(subscribe_dialog.request(
                    method='SUBSCRIBE',
                    headers={'Expires': '1800',
                             'Event': 'dialog',
                             'Accept': 'application/dialog-info+xml'}
                    ), timeout=2)

    received_request = yield from callback_complete

    assert response.status_code == 200
    assert response.status_message == 'OK'
    assert received_request.method == 'SUBSCRIBE'

    server_app.close()


@asyncio.coroutine
def test_response_501(test_server, protocol, loop):
    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
    server = yield from test_server(server_app)
    peer = yield from app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    from_details = 'sip:{user}@{host}:{port}'.format(
        user=server.sip_config['user'],
        host=server.sip_config['client_host'],
        port=server.sip_config['client_port']
    )
    to_details = 'sip:666@{host}:{port}'.format(
        host=server.sip_config['server_host'],
        port=server.sip_config['server_port']
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    response = yield from asyncio.wait_for(subscribe_dialog.request(
                    method='SUBSCRIBE',
                    headers={'Expires': '1800',
                             'Event': 'dialog',
                             'Accept': 'application/dialog-info+xml'}
                    ), timeout=2)

    assert response.status_code == 501
    assert response.status_message == 'Not Implemented'
    server_app.close()


@asyncio.coroutine
def test_exception_in_handler(test_server, protocol, loop):

    @asyncio.coroutine
    def handler(dialog, request):
        raise RuntimeError('TestError')

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': handler})
    server = yield from test_server(server_app)

    peer = yield from app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    from_details = 'sip:{user}@{host}:{port}'.format(
        user=server.sip_config['user'],
        host=server.sip_config['client_host'],
        port=server.sip_config['client_port']
    )
    to_details = 'sip:666@{host}:{port}'.format(
        host=server.sip_config['server_host'],
        port=server.sip_config['server_port']
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    response = yield from asyncio.wait_for(subscribe_dialog.request(
                    method='SUBSCRIBE',
                    headers={'Expires': '1800',
                             'Event': 'dialog',
                             'Accept': 'application/dialog-info+xml'}
                    ), timeout=2)

    assert response.status_code == 500
    assert response.status_message == 'Server Internal Error'
    server_app.close()


async def test_notify(test_server, protocol, loop):
    callback_complete = loop.create_future()

    async def subscribe(dialog, request):
        assert len(dialog.peer.subscriber) == 1
        dialog.reply(request, status_code=200)
        await asyncio.sleep(0.2)
        await dialog.request(method='NOTIFY', payload='1')

    async def notify(dialog, request):
        callback_complete.set_result(request)

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': subscribe})
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    from_details = 'sip:{user}@{host}:{port}'.format(
        user=server.sip_config['user'],
        host=server.sip_config['client_host'],
        port=server.sip_config['client_port']
    )
    to_details = 'sip:666@{host}:{port}'.format(
        host=server.sip_config['server_host'],
        port=server.sip_config['server_port']
    )

    client_router = aiosip.Router()
    client_router['notify'] = notify

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
        router=client_router
    )

    response = await asyncio.wait_for(subscribe_dialog.request(
                    method='SUBSCRIBE',
                    headers={'Expires': '1800',
                             'Event': 'dialog',
                             'Accept': 'application/dialog-info+xml'}
                    ), timeout=2)

    received_notify = await callback_complete

    assert response.status_code == 200
    assert response.status_message == 'OK'

    assert received_notify.method == 'NOTIFY'
    assert received_notify.payload == '1'

    server_app.close()
