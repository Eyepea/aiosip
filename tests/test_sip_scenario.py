import aiosip
import pytest
import asyncio


async def test_notify(test_server, protocol, loop, from_details, to_details):
    notify_list = [0, 1, 2, 3, 4]
    subscribe_future = loop.create_future()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.subscribe

        async def subscribe(request, msg):
            dialog = await request.prepare(status_code=200)
            await asyncio.sleep(0.1)

            for i in notify_list:
                await dialog.notify(payload=str(i))
            subscribe_future.set_result(None)

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

    await server_app.close()
    await app.close()


async def test_authentication(test_server, protocol, loop, from_details, to_details):
    password = 'abcdefg'
    received_messages = list()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.subscribe

        async def subscribe(request, message):
            dialog = request._create_dialog()

            received_messages.append(message)
            assert not dialog.validate_auth(message, password)
            await dialog.unauthorized(message)

            async for message in dialog:
                received_messages.append(message)
                assert dialog.validate_auth(message, password)
                await dialog.reply(message, 200)

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

    await server_app.close()
    await app.close()


async def test_invite(test_server, protocol, loop, from_details, to_details):
    call_established = loop.create_future()
    call_disconnected = loop.create_future()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)
            return self.invite

        async def invite(request, message):
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

    await app.close()
    await server_app.close()


async def test_cancel(test_server, protocol, loop, from_details, to_details):
    cancel_future = loop.create_future()

    class Dialplan(aiosip.BaseDialplan):

        async def resolve(self, *args, **kwargs):
            await super().resolve(*args, **kwargs)

            if kwargs['message'].method == 'SUBSCRIBE':
                return self.subscribe
            elif kwargs['message'].method == 'CANCEL':
                return self.cancel

        async def subscribe(dialog, request):
            pending_subscription.cancel()

        async def cancel(dialog, request):
            cancel_future.set_result(request)

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
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

    await app.close()
    await server_app.close()
