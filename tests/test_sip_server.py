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
        local_addr=(server.sip_config['client_host'], server.sip_config['client_port']),
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(server.sip_config['user'], server.sip_config['client_host'], server.sip_config['client_port'])),
        to_details=aiosip.Contact.from_header('sip:666@{}:{}'.format(server.sip_config['server_host'], server.sip_config['server_port'])),
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
        local_addr=(server.sip_config['client_host'], server.sip_config['client_port']),
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(server.sip_config['user'], server.sip_config['client_host'], server.sip_config['client_port'])),
        to_details=aiosip.Contact.from_header('sip:666@{}:{}'.format(server.sip_config['server_host'], server.sip_config['server_port'])),
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
        local_addr=(server.sip_config['client_host'], server.sip_config['client_port']),
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header('sip:{}@{}:{}'.format(server.sip_config['user'], server.sip_config['client_host'], server.sip_config['client_port'])),
        to_details=aiosip.Contact.from_header('sip:666@{}:{}'.format(server.sip_config['server_host'], server.sip_config['server_port'])),
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
