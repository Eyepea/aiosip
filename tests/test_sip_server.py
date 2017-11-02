import aiosip


async def test_subscribe(test_server, protocol, loop):
    callback_complete = loop.create_future()

    async def handler(dialog, request):
        dialog.reply(request, status_code=200)
        callback_complete.set_result(request)

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': handler})
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

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    responses = list()
    headers = {
        'Expires': '1800',
        'Event': 'dialog',
        'Accept': 'application/dialog-info+xml'
    }
    async for response in subscribe_dialog.request(method='SUBSCRIBE', headers=headers):
        responses.append(response)

    received_request = await callback_complete

    assert len(responses) == 1
    assert responses[0].status_code == 200
    assert responses[0].status_message == 'OK'
    assert received_request.method == 'SUBSCRIBE'

    server_app.close()


async def test_response_501(test_server, protocol, loop):
    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
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

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    responses = list()
    headers = {
        'Expires': '1800',
        'Event': 'dialog',
        'Accept': 'application/dialog-info+xml'
    }
    async for response in subscribe_dialog.request(method='SUBSCRIBE', headers=headers):
        responses.append(response)

    assert len(responses) == 1
    assert responses[0].status_code == 501
    assert responses[0].status_message == 'Not Implemented'
    server_app.close()


async def test_exception_in_handler(test_server, protocol, loop):

    async def handler(dialog, request):
        raise RuntimeError('TestError')

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': handler})
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

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    responses = list()
    headers = {
        'Expires': '1800',
        'Event': 'dialog',
        'Accept': 'application/dialog-info+xml'
    }
    async for response in subscribe_dialog.request(method='SUBSCRIBE', headers=headers):
        responses.append(response)

    assert len(responses) == 1
    assert responses[0].status_code == 500
    assert responses[0].status_message == 'Server Internal Error'
    server_app.close()
