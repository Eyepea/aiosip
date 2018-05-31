"""
Same structure as aiohttp.web.Application
"""
import asyncio
import logging
import sys
import traceback
from collections import MutableMapping
from contextlib import suppress

import aiodns

from . import __version__, exceptions
from .contact import Contact
from .dialog import Dialog
from .dialplan import BaseDialplan
from .message import Request, Response
from .peers import TCPConnector, UDPConnector, WSConnector
from .protocol import TCP, UDP, WS
from .via import Via

__all__ = ['Application']




LOG = logging.getLogger(__name__)

DEFAULTS = {
    'user_agent': 'Python/{0[0]}.{0[1]}.{0[2]} aiosip/{1}'.format(sys.version_info, __version__),
    'override_contact_host': None,
}


def get_branch(header):
    # TODO: hack
    position = header.find(';branch=')
    if position == -1:
        raise LookupError('Not branch found')
    return header[header.find(';branch=') + 8:]


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

        self.defaults = defaults or DEFAULTS

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
        async def send(status_code):
            connector = self._connectors[type(protocol)]
            peer = await connector.get_peer_via(message.headers['Via'], protocol=protocol)

            peer.send_message(Response(
                status_code=status_code,
                status_message=None,
                headers={'CSeq': message.headers['CSeq'],
                         'Via': message.headers['Via']},
                from_details=message.to_details,
                to_details=message.from_details,
                contact_details=Contact.from_header('"Anonymous" <sip:anonymous@anonymous.invalid>'),
                payload=None,
            ))

        if isinstance(message, Request):
            try:
                await self._received_request(protocol, message)
            except exceptions.SIPError as err:
                await send(status_code=err.status_code)

        elif isinstance(message, Response):
            try:
                await self._received_response(message)
            except Exception:
                LOG.exception("Failed to handle response")

    async def _received_request(self, protocol, message):
        branch = get_branch(message.headers['Via'])
        transaction = self._transactions.get((branch, message.method))
        if transaction:
            await transaction.received_request(message)

        # If we got a CANCEL, look for a matching INVITE
        elif message.method == 'CANCEL':
            transaction = self._transactions.get((branch, 'INVITE'))
            if not transaction:
                raise exceptions.SIPTransactionDoesNotExist(
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
                raise exceptions.SIPTransactionDoesNotExist("Dialog does not exist")

        # Handle out-of-dialog requests
        else:
            result = await self._run_dialplan(protocol, message)
            if result:
                # TODO: implement
                pass

            # If OPTIONS was unhandled, use a default implementation
            elif message.method == 'OPTIONS':
                # TODO: fix
                raise exceptions.SIPMethodNotAllowed("Method not allowed")

            elif message.method != 'ACK':
                raise exceptions.SIPMethodNotAllowed("Method not allowed")

    async def _received_response(self, message):

        branch = get_branch(message.headers['Via'])
        transaction = self._transactions.get((branch, message.method))
        if transaction:
            await transaction.received_response(message)

    async def _run_dialplan(self, protocol, msg):
        call_id = msg.headers['Call-ID']
        connector = self._connectors[type(protocol)]
        peer = await connector.get_peer_via(msg.headers['Via'], protocol=protocol)

        try:
            route = await self.dialplan.resolve(
                method=msg.method,
                message=msg,
                protocol=peer.protocol,
                local_addr=peer.local_addr,
                remote_addr=peer.peer_addr
            )

            if not route or not asyncio.iscoroutinefunction(route):
                raise exceptions.SIPNotImplemented()

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
            raise exceptions.SIPServerError(payload=payload)

    async def _call_route(self, peer, route, msg):
        # for middleware_factory in reversed(self._middleware):
        #     route = await middleware_factory(route)

        class Request:
            def __init__(self, transaction):
                self.transaction = transaction

            def accept(self, *args, **kwargs):
                pass

            def reject(self, *, status_code):
                pass

        from .transaction import start_server_transaction
        transaction = await start_server_transaction(msg, peer)
        await route(Request(transaction))

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
