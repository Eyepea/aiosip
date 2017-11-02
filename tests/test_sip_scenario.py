import aiosip
import asyncio


async def test_notify(test_server, protocol, loop, from_details, to_details):
    notify_list = [0, 1, 2, 3, 4]
    received_notify_futures = [loop.create_future() for _ in notify_list]

    async def subscribe(dialog, request):
        assert len(dialog.peer.subscriber) == 1
        dialog.reply(request, status_code=200)
        await asyncio.sleep(0.1)

        for i in notify_list:
            async for rep in dialog.request(method='NOTIFY', payload=str(i)):
                assert rep.status_code == 200

    async def notify(dialog, request):
        received_notify_futures[int(request.payload)].set_result(request)
        dialog.reply(request, status_code=200)

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

    responses = list()
    headers = {'Expires': '1800', 'Event': 'dialog', 'Accept': 'application/dialog-info+xml'}
    async for response in subscribe_dialog.request(method='SUBSCRIBE', headers=headers):
        responses.append(response)

    done, pending = await asyncio.wait(received_notify_futures, return_when=asyncio.ALL_COMPLETED, timeout=1)
    received_notify = [f.result() for f in done]
    assert len(pending) == 0

    assert len(responses) == 1
    assert responses[0].status_code == 200
    assert responses[0].status_message == 'OK'
    assert all((r.method == 'NOTIFY' for r in received_notify))

    server_app.close()


async def test_authentification(test_server, protocol, loop, from_details, to_details):
    password = 'abcdefg'
    received_request = list()

    async def subscribe(dialog, request):
        if dialog.validate_auth(request, password):
            received_request.append(request)
            dialog.reply(request, 200)
        else:
            received_request.append(request)
            dialog.unauthorized(request)

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

    responses = list()
    headers = {'Expires': '1800', 'Event': 'dialog', 'Accept': 'application/dialog-info+xml'}
    async for response in subscribe_dialog.request(method='SUBSCRIBE', headers=headers):
        responses.append(response)

    assert len(responses) == 1
    assert len(received_request) == 2
    assert 'Authorization' in received_request[1].headers
    assert responses[0].status_code == 200
    assert responses[0].status_message == 'OK'

    server_app.close()
