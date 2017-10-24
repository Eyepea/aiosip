import asyncio

import aiosip
import pytest


pytest_plugins = ['aiosip.pytest_plugin']


class TestServer:
    def __init__(self, app, *, loop=None, host='127.0.0.1'):
        self.loop = loop
        self.host = host
        self.app = app
        self._loop = loop

    @asyncio.coroutine
    def start_server(self, protocol, *, loop=None):
        self.handler = self.app.run(
            protocol=protocol,
            local_addr=(self.sip_config['server_host'], self.sip_config['server_port'])
        )
        return self.handler

    @asyncio.coroutine
    def close(self):
        pass

    @property
    def sip_config(self):
        return {
            'client_host': self.host,
            'client_port': 7000,
            'server_host': self.host,
            'server_port': 6000,
            'user': 'pytest',
            'realm': 'example.com'
        }


class TestProxy(TestServer):
    @property
    def sip_config(self):
        return {
            'server_host': self.host,
            'server_port': 8000,
        }


@pytest.fixture(params=['udp', 'tcp'])
def protocol(request):
    if request.param == 'udp':
        return aiosip.UDP
    elif request.param == 'tcp':
        return aiosip.TCP
    pytest.fail('Test requested unknown protocol: {}'.format(request.param))


@pytest.yield_fixture
def test_server(protocol, loop):
    servers = []

    @asyncio.coroutine
    def go(handler, **kwargs):
        server = TestServer(handler)
        yield from server.start_server(protocol, loop=loop, **kwargs)
        servers.append(server)
        return server

    yield go

    @asyncio.coroutine
    def finalize():
        while servers:
            yield from servers.pop().close()

    loop.run_until_complete(finalize())


@pytest.yield_fixture
def test_proxy(protocol, loop):
    servers = []

    @asyncio.coroutine
    def go(handler, **kwargs):
        server = TestProxy(handler)
        yield from server.start_server(protocol, loop=loop, **kwargs)
        servers.append(server)
        return server

    yield go

    @asyncio.coroutine
    def finalize():
        while servers:
            yield from servers.pop().close()

    loop.run_until_complete(finalize())
