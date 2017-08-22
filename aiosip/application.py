"""
Same structure as aiohttp.web.Application
"""
import uuid

__all__ = ['Application']

import asyncio
from collections import MutableMapping
import weakref

from .dialog import Dialog
from .protocol import UDP
from .contact import Contact

from .log import application_logger


class Router(object):
    def __init__(self):
        self.routes = {}

    def add_route(self, method, handler):
        self.routes[method] = handler


class Application(MutableMapping):

    def __init__(self, *, logger=application_logger, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self.logger = logger
        self._finish_callbacks = []
        self.loop = loop
        self._dialogs = weakref.WeakValueDictionary()
        self._state = {}
        self._protocols = {}
        self._transports = {}
        self.router = Router()

    @asyncio.coroutine
    def start_dialog(self,
                     from_uri,
                     to_uri,
                     contact_uri=None,
                     call_id=None,
                     protocol=UDP,
                     local_addr=None,
                     remote_addr=None,
                     password='',
                     dialog=Dialog):

        if local_addr is None:
            contact = Contact.from_header(contact_uri if contact_uri else from_uri)
            local_addr = (contact['uri']['host'],
                          contact['uri']['port'])
        if remote_addr is None:
            contact = Contact.from_header(to_uri)
            remote_addr = (contact['uri']['host'],
                           contact['uri']['port'])

        proto = yield from self.create_connection(protocol, local_addr, remote_addr)

        if not call_id:
            call_id = str(uuid.uuid4())

        dlg = dialog(app=self,
                     from_uri=from_uri,
                     to_uri=to_uri,
                     contact_uri=contact_uri,
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
    def stop_dialog(self, dialog):
        dialog.callbacks = {}
        del self._dialogs[dialog['call_id']]

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
            self._transports[protocol, local_addr, remote_addr] = trans

        yield from proto.ready
        return proto

    @asyncio.coroutine
    def handle_incoming(self, protocol, msg, addr, route):
        local_addr = (msg.to_details['uri']['host'],
                      msg.to_details['uri']['port'])

        remote_addr = (msg.contact_details['uri']['host'],
                       msg.contact_details['uri']['port'])

        proto = yield from self.create_connection(protocol, local_addr, remote_addr)
        dlg = Dialog(app=self,
                     from_uri=msg.headers['From'],
                     to_uri=msg.headers['To'],
                     call_id=msg.headers['Call-ID'],
                     protocol=proto,
                     local_addr=local_addr,
                     remote_addr=remote_addr,
                     password=None,
                     loop=self.loop)

        self._dialogs[msg.headers['Call-ID']] = dlg
        yield from route(dlg, msg)

    def dispatch(self, protocol, msg, addr):
        # key = (protocol, msg.from_details.from_repr(), msg.to_details['uri'].short_uri(), msg.headers['Call-ID'])
        key = msg.headers['Call-ID']

        if key in self._dialogs:
            self._dialogs[key].receive_message(msg)
        else:
            self.logger.debug('A new dialog starts...')
            route = self.router.routes.get(msg.method)
            if route:
                self.loop.call_soon(asyncio.ensure_future, self.handle_incoming(protocol, msg, addr, route))

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
