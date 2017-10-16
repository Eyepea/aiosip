import asyncio
import logging

from . import message


LOG = logging.getLogger(__name__)

CLIENT = 0
SERVER = 1


class UDP(asyncio.DatagramProtocol):
    def __init__(self, app, loop):
        self.app = app
        self.loop = loop
        self.transport = None
        self.ready = asyncio.Future()

    def send_message(self, msg, addr):
        msg.headers['Via'] %= {'protocol': UDP.__name__.upper()}
        LOG.debug('Sent via UDP: "%s"', msg)
        self.transport.sendto(str(msg).encode(), addr)

    def connection_made(self, transport):
        self.transport = transport
        self.ready.set_result(self.transport)

    def datagram_received(self, data, addr):
        msg = data.decode()
        LOG.debug('Received via UDP: "%s"', msg)
        msg_obj = message.Message.from_raw_message(msg)

        asyncio.ensure_future(self.app.dispatch(self, msg_obj, addr))

    # def error_received(self, exc):
    #     print('Error received:', exc)
    #
    # def connection_lost(self, exc):
    #     print("Socket closed, stop the event loop")


class TCP(asyncio.Protocol):
    def __init__(self, app, loop):
        self.app = app
        self.loop = loop
        self.transport = None
        self.ready = asyncio.Future()

    def send_message(self, msg, addr=None):
        msg.headers['Via'] %= {'protocol': TCP.__name__.upper()}
        LOG.debug('Sent via TCP: "%s"', msg)
        self.transport.write(str(msg).encode())

    def connection_made(self, transport):
        peer = transport.get_extra_info('peername')
        LOG.debug('TCP connection made to %s', peer)
        self.transport = transport
        self.ready.set_result(self.transport)

    def data_received(self, data):

        if data == b'\r\n\r\n':
            return
        msg = data.decode()
        LOG.debug('Received via TCP: "%s"', msg)
        msg_obj = message.Message.from_raw_message(msg)
        asyncio.ensure_future(self.app.dispatch(self, msg_obj, None))

    def connection_lost(self, error):
        LOG.debug('Connection lost from %s: %s', self.transport.get_extra_info('peername'), error)
        super().connection_lost(error)
        # self.app._connection_lost(self)
