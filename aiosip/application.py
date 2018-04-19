"""
Same structure as aiohttp.web.Application
"""
import sys
import asyncio
import logging
import aiodns
from contextlib import suppress
import traceback

__all__ = ['Application']

from collections import MutableMapping

from . import __version__
from .dialog import Dialog
from .dialplan import BaseDialplan
from .protocol import UDP, TCP, WS
from .peers import UDPConnector, TCPConnector, WSConnector
from .message import Response
from .contact import Contact
from .via import Via


LOG = logging.getLogger(__name__)

DEFAULTS = {
    'user_agent': 'Python/{0[0]}.{0[1]}.{0[2]} aiosip/{1}'.format(sys.version_info, __version__),
    'override_contact_host': None,
    'dialog_closing_delay': 30
}


class Application(MutableMapping):

    def __init__(self, *,
                 loop=None,
                 dialog_factory=Dialog,
                 middleware=(),
                 defaults=None,
                 debug=False,
                 dialplan=BaseDialplan(),
                 dns_resolver=aiodns.DNSResolver()
                 ):

        if loop is None:
            loop = asyncio.get_event_loop()

        if defaults:
            self.defaults = {**DEFAULTS, **defaults}
        else:
            self.defaults = DEFAULTS

        self.debug = debug
        self.dns = dns_resolver
        self._finish_callbacks = []
        self._state = {}
        self._dialogs = {}
        self._connectors = {UDP: UDPConnector(self, loop=loop),
                            TCP: TCPConnector(self, loop=loop),
                            WS: WSConnector(self, loop=loop)}
        self._middleware = middleware
        self._tasks = list()

        self.dialplan = dialplan
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

    async def connect(self, remote_addr, protocol=UDP, *, local_addr=None):
        connector = self._connectors[protocol]
        peer = await connector.create_peer(remote_addr, local_addr=local_addr)
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

    async def _call_route(self, peer, route, msg):
        for middleware_factory in reversed(self._middleware):
            route = await middleware_factory(route)

        app = self
        call_id = msg.headers['Call-ID']

        # TODO: refactor
        class Request:
            def __init__(self):
                self.app = app
                self.dialog = None

            def _create_dialog(self):
                if not self.dialog:
                    self.dialog = peer._create_dialog(
                        method=msg.method,
                        from_details=Contact.from_header(msg.headers['To']),
                        to_details=Contact.from_header(msg.headers['From']),
                        call_id=call_id,
                    )
                return self.dialog

            async def prepare(self, status_code, *args, **kwargs):
                dialog = self._create_dialog()

                await dialog.reply(msg, status_code, *args, **kwargs)
                if status_code >= 300:
                    await dialog.close()
                    return None

                return dialog

        request = Request()
        await route(request, msg)

    async def _dispatch(self, protocol, msg, addr):
        call_id = msg.headers['Call-ID']
        dialog = self._dialogs.get(frozenset((msg.to_details.details,
                                              msg.from_details.details,
                                              call_id)))

        if dialog:
            await dialog.receive_message(msg)
            return

        # If we got an ACK, but nowhere to deliver it, drop it. If we
        # got a response without an associated message (likely a stale
        # retransmission, drop it)
        if isinstance(msg, Response) or msg.method == 'ACK':
            return

        await self._run_dialplan(protocol, msg)

    async def _run_dialplan(self, protocol, msg):
        call_id = msg.headers['Call-ID']
        via_header = msg.headers['Via']

        # TODO: isn't multidict supposed to only return the first header?
        if isinstance(via_header, list):
            via_header = via_header[0]

        connector = self._connectors[type(protocol)]
        via = Via.from_header(via_header)
        via_addr = via['host'], int(via['port'])
        peer = await connector.get_peer(protocol, via_addr)

        async def reply(*args, **kwargs):
            dialog = peer._create_dialog(
                method=msg.method,
                from_details=Contact.from_header(msg.headers['To']),
                to_details=Contact.from_header(msg.headers['From']),
                call_id=call_id,
            )

            await dialog.reply(*args, **kwargs)
            await dialog.close(fast=True)

        try:
            route = await self.dialplan.resolve(
                username=msg.from_details['uri']['user'],
                method=msg.method,
                protocol=peer.protocol,
                local_addr=peer.local_addr,
                remote_addr=peer.peer_addr
            )

            if not route or not asyncio.iscoroutinefunction(route):
                await reply(msg, status_code=501)
                return

            t = asyncio.ensure_future(self._call_route(peer, route, msg))
            self._tasks.append(t)
            await t
        except asyncio.CancelledError:
            pass
        except Exception as e:
            LOG.exception(e)
            payload = None
            if self.debug:
                with suppress(Exception):
                    payload = traceback.format_exc()
            await reply(msg, status_code=500, payload=payload)

    def _connection_lost(self, protocol):
        connector = self._connectors[type(protocol)]
        connector.connection_lost(protocol)
        # for task in self._tasks:
        #     task.cancel()

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

    async def close(self):
        for connector in self._connectors.values():
            await connector.close()
        for task in self._tasks:
            task.cancel()

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
