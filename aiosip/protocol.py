import asyncio
import logging

from . import message


LOG = logging.getLogger(__name__)


class UDP(asyncio.DatagramProtocol):
    def __init__(self, peer, loop):
        self.peer = peer
        self.via = 'UDP'
        self.loop = loop
        self.transport = None
        self.ready = asyncio.Future()

    def send_message(self, msg, addr):
        if isinstance(msg.headers['Via'], str):
            msg.headers['Via'] %= {'protocol': self.via}
        else:
            msg.headers['Via'][0] %= {'protocol': self.via}

        LOG.log(5, 'Sending to: "%s" via UDP: "%s"', addr, msg)
        self.transport.sendto(msg.encode(), addr)

    def connection_lost(self, error):
        self.peer._connection_lost(self)

    def connection_made(self, transport):
        self.transport = transport
        self.ready.set_result(self.transport)

    def datagram_received(self, data, addr):
        if data == b'\r\n\r\n':
            return

        headers, data = data.split(b'\r\n\r\n', 1)
        msg = message.Message.from_raw_headers(headers)
        msg._raw_payload = data
        LOG.log(5, 'Received from "%s" via UDP: "%s"', addr, msg)
        asyncio.ensure_future(self.peer._dispatch(self, msg, addr))


class TCP(asyncio.Protocol):
    def __init__(self, app, loop):
        self.app = app
        self.via = 'TCP'
        self.loop = loop
        self.transport = None
        self.ready = asyncio.Future()
        self._data = b''

    def send_message(self, msg, addr=None):
        if isinstance(msg.headers['Via'], str):
            msg.headers['Via'] %= {'protocol': self.via}
        else:
            msg.headers['Via'][0] %= {'protocol': self.via}

        LOG.log(5, 'Sent via TCP: "%s"', msg)
        self.transport.write(msg.encode())

    def connection_lost(self, error):
        self.app._connection_lost(self)

    def connection_made(self, transport):
        peer = transport.get_extra_info('peername')
        LOG.debug('TCP connection made to %s', peer)
        self.transport = transport
        self.ready.set_result(self.transport)

    def data_received(self, data):
        LOG.log(3, 'Received on socket %s', data)
        if data == b'\r\n\r\n':
            return

        self._data += data
        while b'\r\n\r\n' in self._data:
            headers, self._data = self._data.split(b'\r\n\r\n', 1)
            msg = message.Message.from_raw_headers(headers)
            content_length = int(msg.headers['Content-Length'])
            msg._raw_payload, self._data = self._data[:content_length], self._data[content_length:]
            # assert len(msg._raw_payload) == int(msg.headers['Content-Length'])
            LOG.log(5, 'Received via TCP: "%s"', msg)
            asyncio.ensure_future(self.app._dispatch(self, msg, None))


class WS:
    def __init__(self, app, loop, local_addr, peer_addr, websocket):
        self.app = app
        self.loop = loop
        self.local_addr = local_addr
        self.peer_addr = peer_addr
        if isinstance(peer_addr, str) and peer_addr.startswith('wss:'):
            self.via = 'WSS'
        else:
            self.via = 'WS'
        self.transport = self
        self.websocket = websocket
        self.websocket_pump = asyncio.ensure_future(self.run())

    def close(self):
        asyncio.ensure_future(self.websocket.close())

    def get_extra_info(self, key):
        if key == 'sockname':
            return self.local_addr
        elif key == 'peername':
            return self.peer_addr

    def send_message(self, msg, addr):
        if isinstance(msg.headers['Via'], str):
            msg.headers['Via'] %= {'protocol': self.via}
        else:
            msg.headers['Via'][0] %= {'protocol': self.via}

        LOG.log(5, 'Sending via %s: "%s"', self.via, msg)
        asyncio.ensure_future(self.websocket.send(msg.encode().decode('utf8')))

    async def run(self):
        while self.websocket.open:
            try:
                data = await self.websocket.recv()
            except Exception:
                break
            if isinstance(data, str):
                data = data.encode('utf8')
            headers, data = data.split(b'\r\n\r\n', 1)
            msg = message.Message.from_raw_headers(headers)
            msg._raw_payload = data
            LOG.log(5, 'Received via %s: "%s"', self.via, msg)
            asyncio.ensure_future(self.app._dispatch(self, msg, self.peer_addr))

        await self.websocket.close()
        self.app._connection_lost(self)
