import aiosip


async def test_subscribe(test_server, protocol, loop, from_details, to_details, close_order):
    callback_complete = loop.create_future()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)

            return self.on_subscribe

        async def on_subscribe(self, request, message):
            await request.prepare(status_code=200)
            callback_complete.set_result(message)

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop, dialplan=Dialplan())
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

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()


async def test_response_501(test_server, protocol, loop, from_details, to_details, close_order):
    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
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

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()


async def test_exception_in_handler(test_server, protocol, loop, from_details, to_details, close_order):

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)

            return self.on_subscribe

        async def on_subscribe(self, request, message):
            raise RuntimeError('Test error')

    app = aiosip.Application(loop=loop)

    server_app = aiosip.Application(loop=loop, dialplan=Dialplan())
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

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()
