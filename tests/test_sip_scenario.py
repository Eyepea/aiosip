import aiosip
import pytest
import asyncio


async def test_notify(test_server, protocol, loop, from_details, to_details, close_order):
    notify_list = [0, 1, 2, 3, 4]
    subscribe_future = loop.create_future()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.subscribe

        async def subscribe(self, request, msg):
            expires = int(msg.headers['Expires'])
            dialog = await request.prepare(status_code=200, headers={'Expires': expires})
            await asyncio.sleep(0.1)

            for i in notify_list:
                await dialog.notify(payload=str(i))
            subscribe_future.set_result(None)

            async for msg in dialog:
                if msg.method == 'SUBSCRIBE':
                    expires = int(msg.headers['Expires'])
                    await dialog.reply(msg, status_code=200, headers={'Expires': expires})

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop, dialplan=Dialplan())
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscribe_dialog = await peer.subscribe(
        expires=1800,
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    for expected in notify_list:
        request = await asyncio.wait_for(subscribe_dialog.recv(), timeout=1)
        await subscribe_dialog.reply(request, status_code=200)
        assert int(request.payload) == expected

    await subscribe_future

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()


async def test_authentication(test_server, protocol, loop, from_details, to_details, close_order):
    password = 'abcdefg'
    received_messages = list()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.subscribe

        async def subscribe(self, request, message):
            dialog = request._create_dialog()

            received_messages.append(message)
            assert not dialog.validate_auth(message=message, password=password)
            await dialog.unauthorized(message)

            async for message in dialog:
                received_messages.append(message)
                if dialog.validate_auth(message=message, password=password):
                    await dialog.reply(message, 200)
                else:
                    await dialog.unauthorized(message)

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
        password=password
    )

    assert len(received_messages) == 2
    assert 'Authorization' in received_messages[1].headers

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()


async def test_authentication_rejection(test_server, protocol, loop, from_details, to_details, close_order):
    received_messages = list()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.subscribe

        async def subscribe(self, request, message):
            dialog = request._create_dialog()

            received_messages.append(message)
            await dialog.unauthorized(message)

            async for message in dialog:
                received_messages.append(message)
                await dialog.unauthorized(message)

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop, dialplan=Dialplan())
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(
            server.sip_config['server_host'],
            server.sip_config['server_port'],
        )
    )
    with pytest.raises(aiosip.exceptions.AuthentificationFailed):
        await peer.register(
            expires=1800,
            from_details=aiosip.Contact.from_header(from_details),
            to_details=aiosip.Contact.from_header(to_details),
            password='testing_pass',
        )

    assert len(received_messages) == 3
    assert all(list('Authorization' in message.headers for message in received_messages[1:]))

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()


async def test_invite(test_server, protocol, loop, from_details, to_details, close_order):
    call_established = loop.create_future()
    call_disconnected = loop.create_future()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.invite

        async def invite(self, request, message):
            dialog = await request.prepare(status_code=100)
            await asyncio.sleep(0.1)
            await dialog.reply(message, status_code=180)
            await asyncio.sleep(0.1)
            await dialog.reply(message, status_code=200)
            call_established.set_result(None)

            async for message in dialog:
                await dialog.reply(message, 200)
                if message.method == 'BYE':
                    call_disconnected.set_result(None)
                    break

    app = aiosip.Application(loop=loop, debug=True)
    server_app = aiosip.Application(loop=loop, debug=True, dialplan=Dialplan())
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    call = await peer.invite(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    responses = list()
    async for msg in call.wait_for_terminate():
        responses.append(msg.status_code)
        if msg.status_code == 200:
            await asyncio.sleep(0.1)
            await call.close()

    await call_established
    await call_disconnected

    assert responses == [100, 180, 200]

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()


async def test_cancel(test_server, protocol, loop, from_details, to_details, close_order):
    cancel_future = loop.create_future()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)

            if kwargs['method'] == 'SUBSCRIBE':
                return self.subscribe
            elif kwargs['method'] == 'CANCEL':
                return self.cancel

        async def subscribe(self, request, message):
            pending_subscription.cancel()

        async def cancel(self, request, message):
            cancel_future.set_result(message)

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop, dialplan=Dialplan())
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    pending_subscription = asyncio.ensure_future(peer.subscribe(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    ))

    with pytest.raises(asyncio.CancelledError):
        await pending_subscription

    result = await cancel_future
    assert result.method == 'CANCEL'

    if close_order[0] == 'client':
        await app.close()
        await server_app.close()
    else:
        await server_app.close()
        await app.close()
