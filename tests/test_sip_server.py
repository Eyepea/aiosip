import asyncio

import aiosip


@asyncio.coroutine
def test_subscribe(test_server, protocol, loop):
    callback_complete = loop.create_future()

    @asyncio.coroutine
    def handler(dialog, request):
        # TODO: putting the context manager here guarantees that we
        # close this connection, but its technically broken. Closing
        # the dialog here in turn cancels this coroutine, so it
        # doesn't actually complete properly.
        #
        # Without this, though, the tests don't run, so its a
        # necessary evil for now.
        with dialog:
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

    with subscribe_dialog:
        yield from asyncio.wait_for(
            subscribe_dialog.send(
                method='SUBSCRIBE',
                headers={'Expires': '1800',
                         'Event': 'dialog',
                         'Accept': 'application/dialog-info+xml'}
            ),
            timeout=1
        )

    request = yield from asyncio.wait_for(callback_complete, timeout=1)
    assert request.method == 'SUBSCRIBE'
