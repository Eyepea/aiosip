"""
Same structure as aiohttp.web.Application
"""
import uuid
import asyncio

__all__ = ['Application']

from collections import MutableMapping

from .dialog import Dialog
from .dialplan import Dialplan
from .protocol import UDP, TCP, CLIENT, SERVER
from .contact import Contact

from .log import application_logger


class Application(MutableMapping):

    def __init__(self, *,
                 logger=application_logger,
                 loop=None,
                 dialog_factory=Dialog
                 ):
        if loop is None:
            loop = asyncio.get_event_loop()

        self.logger = logger
        self._finish_callbacks = []
        self.loop = loop
        self._dialogs = {}
        self._state = {}
        self._protocols = {}
        self.dialplan = Dialplan()
        self._dialog_factory = dialog_factory

    @asyncio.coroutine
    def start_dialog(self,
                     from_uri,
                     to_uri,
                     dialog_factory=Dialog,
                     contact_uri=None,
                     call_id=None,
                     protocol=UDP,
                     local_addr=None,
                     remote_addr=None,
                     password=''):

        if local_addr is None:
            contact = Contact.from_header(contact_uri if contact_uri else from_uri)
            local_addr = (contact['uri']['host'],
                          contact['uri']['port'])
        if remote_addr is None:
            contact = Contact.from_header(to_uri)
            remote_addr = (contact['uri']['host'],
                           contact['uri']['port'])

        proto = yield from self.create_connection(protocol, local_addr, remote_addr, mode=CLIENT)

        if not call_id:
            call_id = str(uuid.uuid4())

        dialog = self._dialog_factory()
        dialog.connection_made(app=self,
                               from_uri=from_uri,
                               to_uri=to_uri,
                               call_id=call_id,
                               protocol=proto,
                               contact_uri=contact_uri,
                               local_addr=local_addr,
                               remote_addr=remote_addr,
                               password=password,
                               loop=self.loop)

        self._dialogs[call_id] = dialog
        return dialog

    @asyncio.coroutine
    def stop_dialog(self, dialog):
        dialog.callbacks = {}
        del self._dialogs[dialog['call_id']]

    @asyncio.coroutine
    def create_connection(self, protocol=UDP, local_addr=None, remote_addr=None, mode=CLIENT):

        if protocol not in (UDP, TCP):
            raise ValueError('Impossible to connect with this protocol class')

        if (protocol, local_addr, remote_addr) in self._protocols:
            proto = self._protocols[protocol, local_addr, remote_addr]
            yield from proto.ready
            return proto

        if protocol is UDP:
            trans, proto = yield from self.loop.create_datagram_endpoint(
                self.make_handler(protocol),
                local_addr=local_addr,
                remote_addr=remote_addr,
            )

            self._protocols[protocol, local_addr, remote_addr] = proto
            yield from proto.ready
            return proto

        elif protocol is TCP and mode is CLIENT:
            trans, proto = yield from self.loop.create_connection(
                self.make_handler(protocol),
                local_addr=local_addr,
                host=remote_addr[0],
                port=remote_addr[1])

            self._protocols[protocol, local_addr, remote_addr] = proto
            yield from proto.ready
            return proto

        elif protocol is TCP and mode is SERVER:
            server = yield from self.loop.create_server(
                self.make_handler(protocol),
                host=local_addr[0],
                port=local_addr[1])
            return server

        else:
            raise ValueError('Impossible to connect with this mode and protocol class')

    @asyncio.coroutine
    def handle_incoming(self, protocol, msg, addr, route):
        local_addr = (msg.to_details['uri']['host'],
                      msg.to_details['uri']['port'])

        remote_addr = (msg.contact_details['uri']['host'],
                       msg.contact_details['uri']['port'])

        self._protocols[type(protocol), local_addr, remote_addr] = protocol
        dialog = self._dialog_factory()

        dialog.connection_made(app=self,
                               from_uri=msg.headers['From'],
                               to_uri=msg.headers['To'],
                               call_id=msg.headers['Call-ID'],
                               protocol=protocol,
                               local_addr=local_addr,
                               remote_addr=remote_addr,
                               password=None,
                               loop=self.loop)

        self._dialogs[msg.headers['Call-ID']] = dialog
        yield from route(dialog, msg)

    def connection_lost(self, protocol):
        del self._protocols[type(protocol),
                            protocol.transport.get_extra_info('sockname'),
                            protocol.transport.get_extra_info('peername')]

    def dispatch(self, protocol, msg, addr):
        # key = (protocol, msg.from_details.from_repr(), msg.to_details['uri'].short_uri(), msg.headers['Call-ID'])
        key = msg.headers['Call-ID']

        if key in self._dialogs:
            self._dialogs[key].receive_message(msg)
        else:
            self.logger.debug('A new dialog starts...')
            route = self.dialplan.resolve(msg)
            if route:
                dialog = self.handle_incoming(protocol, msg, addr, route)
                self.loop.call_soon(asyncio.ensure_future, dialog)

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
