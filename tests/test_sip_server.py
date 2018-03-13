import aiosip


async def test_subscribe(test_server, protocol, loop, from_details, to_details):
    callback_complete = loop.create_future()

    async def handler(dialog, request):
        await dialog.reply(request, status_code=200)
        callback_complete.set_result(request)

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': handler})
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    await peer.subscribe(
        expires=1800,
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    received_request = await callback_complete

    assert received_request.method == 'SUBSCRIBE'

    await server_app.close()
    await app.close()


async def test_response_501(test_server, protocol, loop, from_details, to_details):
    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'subscribe': None})
    server = await test_server(server_app)
    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscription = await peer.subscribe(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    assert subscription.status_code == 501
    assert subscription.status_message == 'Not Implemented'

    await server_app.close()
    await app.close()


async def test_exception_in_handler(test_server, protocol, loop, from_details, to_details):

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

    subscription = await peer.subscribe(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    assert subscription.status_code == 500
    assert subscription.status_message == 'Server Internal Error'

    await server_app.close()
    await app.close()
