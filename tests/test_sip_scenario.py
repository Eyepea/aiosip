import aiosip
import pytest
import asyncio


async def test_notify(test_server, protocol, loop, from_details, to_details):
    notify_list = [0, 1, 2, 3, 4]
    received_notify_futures = [loop.create_future() for _ in notify_list]
    subscribe_future = loop.create_future()

    async def subscribe(dialog, request):
        assert len(dialog.peer.subscriber) == 1
        await dialog.reply(request, status_code=200)
        await asyncio.sleep(0.1)

        for i in notify_list:
            await dialog.notify(payload=str(i))
        subscribe_future.set_result(None)

    async def notify(dialog, request):
        await dialog.reply(request, status_code=200)
        received_notify_futures[int(request.payload)].set_result(request)

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': subscribe})
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    client_router = aiosip.Router()
    client_router['notify'] = notify

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
        router=client_router
    )

    response = await subscribe_dialog.subscribe(expires=1800)

    done, pending = await asyncio.wait(received_notify_futures, return_when=asyncio.ALL_COMPLETED, timeout=1)
    received_notify = [f.result() for f in done]
    assert len(pending) == 0

    await subscribe_future
    assert response.status_code == 200
    assert response.status_message == 'OK'
    assert all((r.method == 'NOTIFY' for r in received_notify))

    server_app.close()


async def test_authentification(test_server, protocol, loop, from_details, to_details):
    password = 'abcdefg'
    received_request = list()

    async def subscribe(dialog, request):
        if dialog.validate_auth(request, password):
            received_request.append(request)
            await dialog.reply(request, 200)
        else:
            received_request.append(request)
            await dialog.unauthorized(request)

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': subscribe})
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
        password=password
    )

    response = await subscribe_dialog.subscribe(expires=1800)

    assert len(received_request) == 2
    assert 'Authorization' in received_request[1].headers
    assert response.status_code == 200
    assert response.status_message == 'OK'

    server_app.close()


async def test_invite(test_server, protocol, loop, from_details, to_details):
    ack_future = loop.create_future()

    async def invite(dialog, request):
        await dialog.reply(request, 100)
        await asyncio.sleep(0.1)
        await dialog.reply(request, 180)
        await asyncio.sleep(0.1)
        ack = await dialog.reply(request, 200, wait_for_ack=True)
        ack_future.set_result(ack)

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'INVITE': invite})
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    invite_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    responses = list()
    async for msg in invite_dialog.invite():
        if msg.status_code == 200:
            invite_dialog.ack(msg)
        responses.append(msg)

    ack = await ack_future

    assert len(responses) == 3
    assert responses[0].status_code == 100
    assert responses[1].status_code == 180
    assert responses[2].status_code == 200
    assert ack.method == 'ACK'


async def test_cancel(test_server, protocol, loop, from_details, to_details):
    subscribe_dialog = None
    cancel_future = loop.create_future()

    async def subscribe(dialog, request):
        subscribe_dialog.close()

    async def cancel(dialog, request):
        cancel_future.set_result(request)

    app = aiosip.Application(loop=loop)
    server_app = aiosip.Application(loop=loop)
    server_app.dialplan.add_user('pytest', {'SUBSCRIBE': subscribe, 'CANCEL': cancel})
    server = await test_server(server_app)

    peer = await app.connect(
        protocol=protocol,
        remote_addr=(server.sip_config['server_host'], server.sip_config['server_port'])
    )

    subscribe_dialog = peer.create_dialog(
        from_details=aiosip.Contact.from_header(from_details),
        to_details=aiosip.Contact.from_header(to_details),
    )

    with pytest.raises(asyncio.CancelledError):
        await subscribe_dialog.subscribe()

    result = await cancel_future
    assert result.method == 'CANCEL'
