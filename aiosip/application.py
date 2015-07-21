"""
Same structure as aiohttp.web.Application
"""
import uuid

__all__ = ['Application']

import asyncio

from .dialog import Dialog
from .protocol import UDP

from .log import application_logger


class Application(dict):

    def __init__(self, *, logger=application_logger, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self.logger = logger
        self._finish_callbacks = []
        self.loop = loop
        self._dialogs = {}
        self._protocols = {}

    @asyncio.coroutine
    def start_dialog(self,
                     from_uri,
                     to_uri,
                     call_id=None,
                     protocol=UDP,
                     local_addr=None,
                     remote_addr=None,
                     password='',
                     dialog=Dialog):

        # @todo: generate local and remote addr based on from_uri and to_uri
        # if local_addr is None:
        #     local_addr=(msg.from_details['uri']['host'],
        #                 msg.from_details['uri']['port'])
        # if remote_addr is None:
        #     remote_addr=(msg.to_details['uri']['host'],
        #                  msg.to_details['uri']['port'])

        proto = yield from self.create_connection(protocol, local_addr, remote_addr)

        if not call_id:
            call_id = str(uuid.uuid4())

        dlg = dialog(app=self,
                     from_uri=from_uri,
                     to_uri=to_uri,
                     call_id=call_id,
                     protocol=proto,
                     local_addr=local_addr,
                     remote_addr=remote_addr,
                     password=password,
                     loop=self.loop)

        # self._dialogs[protocol, dlg.from_details.from_repr(), dlg.to_details['uri'].short_uri(), call_id] = dlg
        self._dialogs[call_id] = dlg

        return dlg

    @asyncio.coroutine
    def create_connection(self, protocol, local_addr, remote_addr, mode='client'):
        if (protocol, local_addr, remote_addr) in self._protocols:
            proto = self._protocols[protocol, local_addr, remote_addr]
        else:
            if issubclass(protocol, asyncio.DatagramProtocol):
                trans, proto = yield from self.loop.create_datagram_endpoint(
                    lambda: protocol(app=self, loop=self.loop),
                    local_addr=local_addr,
                    remote_addr=remote_addr,
                )
            elif issubclass(protocol, asyncio.Protocol) and mode == 'client':
                trans, proto = yield from self.loop.create_connection(
                    lambda: protocol(app=self, loop=self.loop),
                    local_addr=local_addr,
                    host=remote_addr[0],
                    port=remote_addr[1])
            elif issubclass(protocol, asyncio.Protocol) and mode == 'server':
                trans, proto = yield from self.loop.create_server(
                    lambda: protocol(app=self, loop=self.loop),
                    host=remote_addr[0],
                    port=remote_addr[1])
            else:
                raise Exception('Impossible to connect with this protocol class')

            self._protocols[protocol, local_addr, remote_addr] = proto

        yield from proto.ready
        return proto

    def dispatch(self, protocol, msg):
        # key = (protocol, msg.from_details.from_repr(), msg.to_details['uri'].short_uri(), msg.headers['Call-ID'])
        key = msg.headers['Call-ID']
        print('='*50)
        # import ipdb; ipdb.set_trace()
        print(key)
        print(self._dialogs)
        print('/'*50)
        if key in self._dialogs:
            self._dialogs[key].receive_message(msg)
        else:
            self.logger.debug('A new dialog starts...')  # @todo: it's a new dialog
            # next(iter(self._dialogs.values())).receive_message(msg)

    def send_message(self, protocol, local_addr, remote_addr, msg):
        if (protocol, local_addr, remote_addr) in self._protocols:
            self._protocols[protocol, local_addr, remote_addr].send_message(msg)
        else:
            raise ValueError('No protocol to send message')

    @asyncio.coroutine
    def finish(self):
        callbacks = self._finish_callbacks
        self._finish_callbacks = []

        for (cb, args, kwargs) in callbacks:
            try:
                res = cb(self, *args, **kwargs)
                if (asyncio.iscoroutine(res) or
                        isinstance(res, asyncio.Future)):
                    yield from res
            except Exception as exc:
                self.loop.call_exception_handler({
                    'message': "Error in finish callback",
                    'exception': exc,
                    'application': self,
                    })

    def register_on_finish(self, func, *args, **kwargs):
        self._finish_callbacks.insert(0, (func, args, kwargs))
