import asyncio

import aiosip


@asyncio.coroutine
def test_subscribe(test_server, protocol, loop):
    callback_complete = loop.create_future()

    @asyncio.coroutine
    def handler(dialog, request):
        response = aiosip.Response.from_request(
            request=request,
            status_code=200,
            status_message='OK'
        )
        dialog.reply(response)
        callback_complete.set_result(request)

    app = aiosip.Application(loop=loop)
    app.dialplan.add_user('pytest', {'SUBSCRIBE': handler})
    server = yield from test_server(app)

    connection = yield from app.connect(
        protocol=protocol,
        local_addr=(server.sip_config['client_host'], server.sip_config['client_port']),
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscribe_dialog = connection.create_dialog(
        from_uri='sip:{}@{}:{}'.format(server.sip_config['user'], server.sip_config['client_host'], server.sip_config['client_port']),
        to_uri='sip:666@{}:{}'.format(server.sip_config['server_host'], server.sip_config['server_port']),
    )

    future = subscribe_dialog.send(
        method='SUBSCRIBE',
        headers={'Expires': '1800',
                 'Event': 'dialog',
                 'Accept': 'application/dialog-info+xml'}
    )

    yield from asyncio.wait_for(future, timeout=1)
    request = yield from asyncio.wait_for(callback_complete, timeout=1)
    assert request.method == 'SUBSCRIBE'
