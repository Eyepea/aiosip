import asyncio

from . import message
from .log import protocol_logger


class UDP(asyncio.DatagramProtocol):
    def __init__(self, app, loop):
        self.app = app
        self.loop = loop
        self.transport = None
        self.ready = asyncio.Future()

    def send_message(self, msg):
        msg.headers['Via'] %= {'protocol': UDP.__name__.upper()}
        protocol_logger.debug('Sent: "%s"', msg)
        self.transport.sendto(str(msg).encode())

    def connection_made(self, transport):
        self.transport = transport
        self.ready.set_result(self.transport)

    def datagram_received(self, data, addr):
        msg = data.decode()
        protocol_logger.debug('Received: "%s"', msg)
        msg_obj = message.Message.from_raw_message(msg)

        self.app.dispatch(UDP, msg_obj)

    # def error_received(self, exc):
    #     print('Error received:', exc)
    #
    # def connection_lost(self, exc):
    #     print("Socket closed, stop the event loop")

