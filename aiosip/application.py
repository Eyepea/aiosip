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
}


class Application(MutableMapping):

    def __init__(self, *,
                 loop=None,
                 middleware=(),
                 defaults=None,
                 debug=False,
                 dialplan=BaseDialplan(),
                 dns_resolver=aiodns.DNSResolver()
                 ):

        if loop is None:
            loop = asyncio.get_event_loop()

        self._state = {}
        self._dialogs = {}
        self._transactions = {}
        self._connectors = {UDP: UDPConnector(self, loop=loop),
                            TCP: TCPConnector(self, loop=loop),
                            WS: WSConnector(self, loop=loop)}
        self._middleware = middleware
        self._tasks = list()

        self.debug = debug
        self.dns = dns_resolver
        self.dialplan = dialplan
        self.loop = loop

    @property
    def peers(self):
        for connector in self._connectors.values():
            yield from connector._peers.values()

    @property
    def dialogs(self):
        yield from set(self._dialogs.values())

    async def connect(self, remote_addr, protocol=UDP, *, local_addr=None, **kwargs):
        connector = self._connectors[protocol]
        peer = await connector.create_peer(remote_addr, local_addr=local_addr, **kwargs)
        return peer

    async def run(self, *, local_addr=None, protocol=UDP, sock=None, **kwargs):
        if not local_addr and not sock:
            raise ValueError('One of "local_addr", "sock" is mandatory')
        elif local_addr and sock:
            raise ValueError('local_addr, sock are mutually exclusive')
        elif not local_addr:
            local_addr = None, None

        connector = self._connectors[protocol]
        server = await connector.create_server(local_addr, sock, **kwargs)
        return server

    async def _dispatch(self, protocol, message, addr):
        if isinstance(message, Request):
            try:
                self._received_request(protocol, message)
            except SIPError as err:
                self.send(status_code=err.status_code)

        elif isinstance(message, Response):
            self._received_response(message)

    async def _received_request(self, protocol, message):
        branch = message.headers['Via'].branch
        transaction = self._transactions.get((branch, message.method))
        if transaction:
            await transaction.received_request(message)

        # If we got a CANCEL, look for a matching INVITE
        elif message.method == 'CANCEL':
            transaction = self._transactions.get((branch, 'INVITE'))
            if not transaction:
                raise SIPTransactionDoesNotExist(
                    "Original transaction does not exist")

            await transaction.received_request(message)

        # Handle in-dialog requests
        elif 'tag' in message.headers['To']:
            dialog = self.find_dialog(message)
            if dialog:
                pass
            elif message.method == 'ACK':
                transaction = self._transactions((branch, 'INVITE'))
                if transaction:
                    transaction.received_request(message)
            else:
                raise SIPTransactionDoesNotExist("Dialog does not exist")

        # Handle out-of-dialog requests
        else:
            result = self._run_dialplan(protocol, message)
            if result:
                # TODO: implement
                pass

            # If OPTIONS was unhandled, use a default implementation
            elif message.method == 'OPTIONS':
                # TODO: fix
                raise SIPMethodNotAllowed("Method not allowed")

            elif message.method != 'ACK':
                raise SIPMethodNotAllowed("Method not allowed")


    async def _received_response(self, message):
        branch = message.headers['Via'].branch
        transaction = self._transactions.get((branch, message.method))
        if transaction:
            await transaction.received_response(message)

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
                inbound=True
            )

            await dialog.reply(*args, **kwargs)
            await dialog.close()

        try:
            route = await self.dialplan.resolve(
                method=msg.method,
                message=msg,
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

    async def _call_route(self, peer, route, msg):
        # for middleware_factory in reversed(self._middleware):
        #     route = await middleware_factory(route)

        from .transaction import start_server_transaction
        request = await start_server_transaction(msg, peer)
        await route(request)

    def _connection_lost(self, protocol):
        connector = self._connectors[type(protocol)]
        connector.connection_lost(protocol)

    async def close(self, timeout=5):
        for dialog in set(self._dialogs.values()):
            try:
                await dialog.close(timeout=timeout)
            except asyncio.TimeoutError:
                pass
        for connector in self._connectors.values():
            await connector.close()
        for task in self._tasks:
            task.cancel()

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
