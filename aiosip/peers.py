import uuid
import asyncio
import logging
import ipaddress
import websockets

from multidict import CIMultiDict

from . import utils
from .contact import Contact
from .protocol import UDP, TCP, WS
from .dialog import Dialog, InviteDialog
from .via import Via

LOG = logging.getLogger(__name__)


class Peer:
    def __init__(self, peer_addr, app, *, loop=None):
        self.peer_addr = peer_addr
        self._app = app
        self._protocol = None
        self._loop = loop
        self._connected_future = asyncio.Future(loop=loop)
        self._disconnected_future = asyncio.Future(loop=loop)

    async def close(self):
        if self._protocol is not None:
            LOG.debug('Closing connection for %s', self)
            self._protocol.transport.close()
            await self._disconnected_future

    def send_message(self, msg):
        self._protocol.send_message(msg, addr=self.peer_addr)

    def _create_dialog(self, method, from_details, to_details, contact_details=None, password=None, call_id=None,
                       headers=None, payload=None, cseq=0, inbound=False, dialog_factory=Dialog, **kwargs):

        from_details.add_tag()

        if not call_id:
            call_id = str(uuid.uuid4())

        if not contact_details:
            host, port = self.local_addr

            # No way to get the public local addr in UDP. Allow an override or select the From host
            # Maybe with https://bugs.python.org/issue31203
            if self._app.defaults['override_contact_host']:
                host = self._app.defaults['override_contact_host']
            elif host == '0.0.0.0' or host.startswith('127.'):
                host = from_details['uri']['host']

            contact_details = Contact(
                {
                    'uri': 'sip:{username}@{host_and_port};transport={protocol}'.format(
                        username=from_details['uri']['user'],
                        host_and_port=utils.format_host_and_port(host, port),
                        protocol=type(self._protocol).__name__.lower()
                    )
                }
            )

        dialog = dialog_factory(
            method=method,
            app=self._app,
            from_details=from_details,
            to_details=to_details,
            contact_details=contact_details,
            call_id=call_id,
            peer=self,
            password=password,
            headers=headers,
            payload=payload,
            cseq=cseq,
            inbound=inbound,
            **kwargs
        )

        LOG.debug('Creating: %s', dialog)
        self._app._dialogs[dialog.dialog_id] = dialog
        self._app._dialogs[
            frozenset((dialog.original_msg.to_details['params'].get('tag'), None, dialog.call_id))
        ] = dialog
        return dialog

    async def request(self, method, from_details, to_details, contact_details=None, password=None, call_id=None,
                      headers=None, cseq=0, payload=None, dialog_factory=Dialog, timeout=None, **kwargs):
        from .message import Request
        from .transaction import start_client_transaction

        if not contact_details:
            host, port = self.local_addr

            if self._app.defaults['override_contact_host']:
                host = self._app.defaults['override_contact_host']
            elif host == '0.0.0.0' or host.startswith('127.'):
                host = from_details['uri']['host']

            contact_details = Contact(
                {
                    'uri': 'sip:{username}@{host_and_port};transport={protocol}'.format(
                        username=from_details['uri']['user'],
                        host_and_port=utils.format_host_and_port(host, port),
                        protocol=type(self._protocol).__name__.lower()
                    )
                })

        message = Request(method, 20, from_details, to_details, contact_details, headers, payload)
        return await start_client_transaction(message, self)

    async def subscribe(self, expires=3600, **kwargs):
        headers = kwargs.get('headers')
        if headers:
            headers['Expires'] = str(expires)

        transaction = await self.request('SUBSCRIBE', **kwargs)
        await transaction.completed()
        return transaction

    async def register(self, expires=3600, **kwargs):

        if expires:
            headers = kwargs.get('headers', CIMultiDict())
            headers['Expires'] = expires
            kwargs['headers'] = headers

        return await self.request('REGISTER', **kwargs)

    async def invite(self, dialog_factory=InviteDialog, **kwargs):

        dialog = self._create_dialog(dialog_factory=dialog_factory, method='INVITE', **kwargs)
        await dialog.start()
        return dialog

    @property
    def protocol(self):
        return type(self._protocol)

    @property
    def connected(self):
        return self._connected_future

    def _connected(self, protocol):
        if not self._connected_future.done():
            self._connected_future.set_result(protocol)

        if self._protocol:
            assert self._protocol == protocol
        else:
            self._protocol = protocol

    def _disconnected(self):
        LOG.debug('Lost connection for %s', self)
        self._protocol = None
        self._disconnected_future.set_result(None)

    def generate_via_headers(self, branch=utils.gen_branch()):
        return f'SIP/2.0/{self._protocol.via} {self.local_addr[0]}:{self.local_addr[1]};branch={branch}'

    @property
    def local_addr(self):
        if self._protocol:
            return self._protocol.transport.get_extra_info('sockname')
        else:
            return None, None

    def __repr__(self):
        return '<{0} {1[0]}:{1[1]} {2}, local_addr={3[0]}:{3[1]}>'.format(
            self.__class__.__name__, self.peer_addr, self.protocol.__name__, self.local_addr)


class BaseConnector:
    def __init__(self, app, *, loop=None):
        self._app = app
        self._loop = loop or asyncio.get_event_loop()

        self._protocols = {}
        self._peers = {}
        self._servers = {}

    async def create_server(self, local_addr, sock, **kwargs):
        return await self._create_server(local_addr, sock, **kwargs)

    async def create_peer(self, peer_addr, local_addr=None, **kwargs):
        try:
            peer_addr = ipaddress.ip_address(peer_addr[0]).exploded, peer_addr[1]
        except ValueError:
            dns = await self._app.dns.query(peer_addr[0], 'A')
            peer_addr = dns[0].host, peer_addr[1]

        try:
            if not local_addr:
                peer = [peer for key, peer in self._peers.items() if key[0] == peer_addr][0]
            else:
                peer = self._peers[(peer_addr, local_addr)]
        except (KeyError, IndexError):
            peer = self._create_peer(peer_addr)
            await self._connect_peer(peer, local_addr, **kwargs)
            LOG.debug('Creating: %s', peer)
            return peer
        else:
            await peer.connected
            return peer

    def _create_peer(self, peer_addr):
        peer = Peer(peer_addr, self._app, loop=self._loop)
        self._peers[(peer_addr, None)] = peer
        return peer

    async def _connect_peer(self, peer, local_addr, **kwargs):
        peer._connected(await self._create_connection(peer_addr=peer.peer_addr, local_addr=local_addr, **kwargs))
        if (peer.peer_addr, None) in self._peers:
            del self._peers[(peer.peer_addr, None)]
        if (peer.peer_addr, peer.local_addr) not in self._peers:
            self._peers[(peer.peer_addr, peer.local_addr)] = peer

    async def get_peer(self, protocol, peer_addr):
        return await self._dispatch(protocol, peer_addr)

    async def get_peer_via(self, via_header, *, protocol):
        if isinstance(via_header, list):
            via_header = via_header[0]

        via = Via.from_header(via_header)
        via_addr = via['host'], int(via['port'])
        return await self.get_peer(protocol, via_addr)

    def connection_lost(self, protocol):
        for key, peer in list(self._peers.items()):
            if peer._protocol == protocol:
                peer._disconnected()
                self._peers.pop(key)

        for key, proto in list(self._protocols.items()):
            if proto == protocol:
                self._protocols.pop(key)

    async def close(self):
        for peer in list(self._peers.values()):
            await peer.close()

        for server in self._servers.values():
            server.close()
            await server.wait_closed()
        self._servers = {}

    async def _create_server(self, local_addr, sock, **kwargs):
        raise NotImplementedError()

    async def _create_connection(self, peer_addr, local_addr, **kwargs):
        raise NotImplementedError()

    async def _dispatch(self, protocol, peer_addr):
        raise NotImplementedError()


class TCPConnector(BaseConnector):
    async def _create_server(self, local_addr, sock, ssl=None):
        server = await self._loop.create_server(
            lambda: TCP(app=self._app, loop=self._loop),
            host=local_addr[0],
            port=local_addr[1],
            sock=sock,
            ssl=ssl
        )
        self._servers[local_addr] = server
        return server

    async def _create_connection(self, peer_addr, local_addr, ssl=None):
        try:
            return self._protocols[(peer_addr, local_addr)]
        except KeyError:
            transport, proto = await self._loop.create_connection(
                lambda: TCP(app=self._app, loop=self._loop),
                host=peer_addr[0],
                port=peer_addr[1],
                local_addr=local_addr,
                ssl=ssl
            )
            local_addr = transport.get_extra_info('sockname')
            self._protocols[(peer_addr, local_addr)] = proto
            return proto

    async def _dispatch(self, protocol, _):
        peer_addr = protocol.transport.get_extra_info('peername')
        local_addr = protocol.transport.get_extra_info('sockname')
        if (peer_addr, local_addr) not in self._protocols:
            self._protocols[(peer_addr, local_addr)] = protocol
        return await self.create_peer(peer_addr, local_addr)


class UDPServer:
    """
    Shim to present a unified server interface.
    """
    def __init__(self, transport):
        self.transport = transport

    def close(self):
        self.transport.close()

    async def wait_closed(self):
        pass


class UDPConnector(BaseConnector):
    async def _create_connection(self, peer_addr, local_addr):
        try:
            return self._protocols[(peer_addr, local_addr)]
        except KeyError:
            transport, proto = await self._loop.create_datagram_endpoint(
                lambda: UDP(app=self._app, loop=self._loop),
                local_addr=local_addr,
                remote_addr=peer_addr
            )
            local_addr = transport.get_extra_info('sockname')
            self._protocols[(peer_addr, local_addr)] = proto
            return proto

    async def _create_server(self, local_addr=None, sock=None):
        if sock and local_addr:
            raise ValueError('local_addr and sock are mutually exclusive')
        elif not sock and not local_addr:
            raise ValueError('One of local_addr, sock is mandatory')

        try:
            return self._servers[local_addr]
        except KeyError:
            transport, proto = await self._loop.create_datagram_endpoint(
                lambda: UDP(app=self._app, loop=self._loop),
                sock=sock,
                local_addr=local_addr
            )
            proto_addr = proto.transport.get_extra_info('sockname')
            if sock:
                assert sock.getsockname() == proto_addr
            else:
                assert local_addr == proto_addr

            server = UDPServer(transport)
            self._servers[local_addr] = server
            return server

    async def _dispatch(self, protocol, peer_addr):
        local_addr = protocol.transport.get_extra_info('sockname')
        if (peer_addr, local_addr) not in self._protocols:
            self._protocols[(peer_addr, local_addr)] = protocol
        return await self.create_peer(peer_addr, local_addr)


class WSConnector(BaseConnector):
    async def _create_connection(self, peer_addr, local_addr):
        try:
            return self._protocols[(peer_addr, local_addr)]
        except KeyError:
            websocket = await websockets.connect(peer_addr, subprotocols=['sip'])
            local_addr = (utils.gen_str(12) + '.invalid', None)
            proto = WS(app=self._app, loop=self._loop,
                       local_addr=local_addr,
                       peer_addr=peer_addr,
                       websocket=websocket)
            self._protocols[(peer_addr, local_addr)] = proto
            return proto

    async def _create_server(self, local_addr, sock):
        async def hello(websocket, path):
            proto = WS(app=self._app, loop=self._loop,
                       local_addr=local_addr,
                       peer_addr=websocket.remote_address,
                       websocket=websocket)
            await proto.websocket_pump

        try:
            return self._servers[local_addr]
        except KeyError:
            server = await websockets.serve(hello, local_addr[0], local_addr[1],
                                            subprotocols=['sip'])
            self._servers[local_addr] = server
            return server

    async def _dispatch(self, protocol, peer_addr):
        local_addr = protocol.local_addr
        if (peer_addr, local_addr) not in self._protocols:
            self._protocols[(peer_addr, local_addr)] = protocol
        return await self.create_peer(peer_addr, local_addr)
