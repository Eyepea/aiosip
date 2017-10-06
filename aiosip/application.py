"""
Same structure as aiohttp.web.Application
"""
import sys
import asyncio
import logging

__all__ = ['Application']

from collections import MutableMapping

from . import __version__
from .dialog import Dialog
from .dialplan import Dialplan
from .protocol import UDP, CLIENT, SERVER
from .connections import Connection
from .message import Request


LOG = logging.getLogger(__name__)


class Application(MutableMapping):

    def __init__(self, *,
                 user_agent=None,
                 loop=None,
                 dialog_factory=Dialog,
                 middleware=()
                 ):
        if loop is None:
            loop = asyncio.get_event_loop()

        if user_agent is None:
            user_agent = 'Python/{0[0]}.{0[1]}.{0[2]} aiosip/{1}'.format(sys.version_info, __version__)

        self._finish_callbacks = []
        self._state = {}
        self._connections = {}
        self._middleware = middleware

        self.dialplan = Dialplan()
        self.dialog_factory = dialog_factory
        self.user_agent = user_agent
        self.loop = loop

    @property
    def dialogs(self):
        for connection in self._connections:
            yield from connection.dialogs.values()

    @property
    def connections(self):
        yield from self._connections.values()

    @asyncio.coroutine
    def connect(self, local_addr, remote_addr, protocol=UDP):
        connection = yield from self._create_connection(local_addr, remote_addr, protocol=protocol, mode=CLIENT)
        return connection

    @asyncio.coroutine
    def run(self, local_addr, protocol=UDP):
        server = yield from self._create_connection(local_addr, protocol=protocol, mode=SERVER)
        return server

    @asyncio.coroutine
    def _create_connection(self, local_addr=None, remote_addr=None, protocol=UDP, mode=CLIENT):

        if (protocol, local_addr, remote_addr) in self._connections:
            return self._connections[protocol, local_addr, remote_addr]

        if issubclass(protocol, asyncio.DatagramProtocol):
            trans, proto = yield from self.loop.create_datagram_endpoint(
                self.make_handler(protocol),
                local_addr=local_addr,
                remote_addr=remote_addr,
            )

            connection = Connection(local_addr, remote_addr, proto, self)
            self._connections[local_addr, remote_addr, protocol] = connection
            yield from proto.ready
            return connection

        elif issubclass(protocol, asyncio.Protocol) and mode is CLIENT:
            trans, proto = yield from self.loop.create_connection(
                self.make_handler(protocol),
                local_addr=local_addr,
                host=remote_addr[0],
                port=remote_addr[1])

            connection = Connection(local_addr, remote_addr, proto, self)
            self._connections[local_addr, remote_addr, protocol] = connection
            yield from proto.ready
            return connection

        elif issubclass(protocol, asyncio.Protocol) and mode is SERVER:
            server = yield from self.loop.create_server(
                self.make_handler(protocol),
                host=local_addr[0],
                port=local_addr[1])
            return server

        else:
            raise ValueError('Impossible to connect with this protocol class')

    def _connection_lost(self, protocol):
        local_addr = protocol.transport.get_extra_info('sockname')
        remote_addr = protocol.transport.get_extra_info('peername')

        try:
            connection = self._connections[local_addr, remote_addr, type(protocol)]
        except KeyError:
            pass
        else:
            connection._connection_lost()

    def dispatch(self, protocol, msg, addr):
        # key = (protocol, msg.from_details.from_repr(), msg.to_details['uri'].short_uri(), msg.headers['Call-ID'])
        key = msg.headers['Call-ID']
        local_addr = protocol.transport.get_extra_info('sockname')
        remote_addr = protocol.transport.get_extra_info('peername')

        if not remote_addr:
            if isinstance(msg, Request):
                remote_addr = (msg.from_details['uri']['host'],
                               msg.from_details['uri']['port'])
            else:
                remote_addr = (msg.to_details['uri']['host'],
                               msg.to_details['uri']['port'])

        connection = self._connections.get((local_addr, remote_addr, type(protocol)))
        if not connection:
            LOG.debug('New connection for %s', remote_addr)
            connection = Connection(local_addr, remote_addr, protocol, self)
            self._connections[local_addr, remote_addr, type(protocol)] = connection

        dialog = connection.dialogs.get(key)
        if not dialog:
            LOG.debug('New dialog for %s, ID: "%s"', remote_addr, key)
            dialog = connection.create_dialog(
                from_uri=msg.headers['To'],
                to_uri=msg.headers['From'],
                password=None,
                call_id=msg.headers['Call-ID'],
                router=self.dialplan.resolve(msg)
            )
        asyncio.ensure_future(dialog.receive_message(msg))

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

    def __repr__(self):
        return "<Application>"

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        return self._state[key]

    def __setitem__(self, key, value):
        self._state[key] = value

    def __delitem__(self, key):
        del self._state[key]

    def __len__(self):
        return len(self._state)

    def __iter__(self):
        return iter(self._state)

    def make_handler(self, protocol):
        return lambda: protocol(app=self, loop=self.loop)
