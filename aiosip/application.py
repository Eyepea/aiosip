"""
Same structure as aiohttp.web.Application
"""
import sys
import asyncio
import logging
import aiodns

__all__ = ['Application']

from collections import MutableMapping

from . import __version__
from .dialog import Dialog
from .dialplan import Dialplan
from .protocol import UDP, TCP
from .peers import UDPConnector, TCPConnector
from .contact import Contact


LOG = logging.getLogger(__name__)

DEFAULTS = {
    'user_agent': 'Python/{0[0]}.{0[1]}.{0[2]} aiosip/{1}'.format(sys.version_info, __version__),
    'override_contact_host': None
}


class Application(MutableMapping):

    def __init__(self, *,
                 loop=None,
                 dialog_factory=Dialog,
                 middleware=(),
                 defaults=None,
                 dialplan=None,
                 dns_resolver=aiodns.DNSResolver()
                 ):

        if loop is None:
            loop = asyncio.get_event_loop()

        if defaults:
            self.defaults = {**DEFAULTS, **defaults}
        else:
            self.defaults = DEFAULTS

        self.dns = dns_resolver
        self._finish_callbacks = []
        self._state = {}
        self._connectors = {UDP: UDPConnector(self, loop=loop),
                            TCP: TCPConnector(self, loop=loop)}
        self._middleware = middleware

        self.dialplan = dialplan or Dialplan()
        self.dialog_factory = dialog_factory
        self.loop = loop

    @property
    def peers(self):
        for connector in self._connectors.values():
            yield from connector._peers.values()

    @property
    def dialogs(self):
        for peer in self.peers:
            yield from peer._dialogs.values()

    async def connect(self, remote_addr, protocol=UDP):
        connector = self._connectors[protocol]
        peer = await connector.create_peer(remote_addr)
        return peer

    async def run(self, *, local_addr=None, protocol=UDP, sock=None):

        if not local_addr and not sock:
            raise ValueError('One of "local_addr", "sock" is mandatory')
        elif local_addr and sock:
            raise ValueError('local_addr, sock are mutually exclusive')
        elif not local_addr:
            local_addr = None, None

        connector = self._connectors[protocol]
        server = await connector.create_server(local_addr, sock)
        return server

    async def dispatch(self, protocol, msg, addr):
        connector = self._connectors[type(protocol)]
        peer = await connector.get_peer(protocol, addr)
        key = msg.headers['Call-ID']
        dialog = peer._dialogs.get(key)
        if not dialog:
            LOG.debug('New dialog for %s, ID: "%s"', peer, key)
            dialog = peer.create_dialog(
                from_details=Contact.from_header(msg.headers['To']),
                to_details=Contact.from_header(msg.headers['From']),
                password=None,
                call_id=msg.headers['Call-ID'],
                router=self.dialplan.resolve(msg)
            )
        await dialog.receive_message(msg)

    def _connection_lost(self, protocol):
        connector = self._connectors[type(protocol)]
        connector.connection_lost(protocol)

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

    def close(self):
        for connector in self._connectors.values():
            connector.close()

    # def __repr__(self):
    #     return "<Application>"

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
