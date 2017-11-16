import asyncio
import logging
import time
import uuid

from collections import defaultdict

from . import utils
from .protocol import UDP, TCP
from .contact import Contact

LOG = logging.getLogger(__name__)


class Peer:
    def __init__(self, peer_addr, app, connector, *, loop=None):
        self.peer_addr = peer_addr
        self.registered = {}
        self.subscriber = defaultdict(dict)
        self._app = app
        self._connector = connector
        self._protocol = None
        self._loop = loop
        self._dialogs = {}
        self._connected_future = asyncio.Future(loop=loop)
        self.closed = False

    @property
    def dialogs(self):
        return self._dialogs

    def close(self):
        if not self.closed:
            self.closed = True
            self.registered = {}
            self.subscriber = defaultdict(dict)
            for dialog in self._dialogs.values():
                dialog._close()
            self._dialogs = {}

            if self._protocol is not None:
                LOG.debug('Closing connection for %s', self)
                self._connector._release(self.peer_addr, self._protocol, should_close=True)
                self._protocol = None

    def send_message(self, msg):
        self._protocol.send_message(msg, addr=self.peer_addr)

    def create_dialog(self, from_details, to_details, contact_details=None, password=None, call_id=None, cseq=0,
                      router=None):

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
                    'uri': 'sip:{username}@{host}:{port};transport={protocol}'.format(
                        username=from_details['uri']['user'],
                        host=host,
                        port=port,
                        protocol=type(self._protocol).__name__.upper()
                    )
                }
            )

        dialog = self._app.dialog_factory(
            app=self._app,
            from_details=from_details,
            to_details=to_details,
            contact_details=contact_details,
            call_id=call_id,
            peer=self,
            password=password,
            cseq=cseq,
            router=router
        )
        LOG.debug('Creating: %s', dialog)
        self._dialogs[call_id] = dialog
        return dialog

    async def proxy_request(self, dialog, msg, timeout=5):
        if msg.method == 'ACK':
            self.send_message(msg)
            return

        proxy_dialog = self._dialogs.get(dialog.call_id)
        if not proxy_dialog:
            router = await self._app.dialplan.resolve(
                    username=dialog.to_details['uri']['user'],
                    protocol=dialog.peer.protocol,
                    local_addr=dialog.peer.local_addr,
                    remote_addr=dialog.peer.peer_addr
            )
            proxy_dialog = self.create_dialog(
                from_details=dialog.from_details,
                to_details=dialog.to_details,
                call_id=dialog.call_id,
                router=router
            )
        elif msg.cseq in proxy_dialog.transactions[msg.method]:
            proxy_dialog.transactions[msg.method][msg.cseq].retransmit()
            return

        if isinstance(msg.headers['Via'], str):
            msg.headers['Via'] = [msg.headers['Via']]

        host, port = self.local_addr
        if self._app.defaults['override_contact_host']:
            host = self._app.defaults['override_contact_host']

        msg.headers['Via'].insert(0, 'SIP/2.0/%(protocol)s {host}:{port};branch={branch}'.format(
                host=host,
                port=port,
                branch=utils.gen_branch(10)
            )
        )

        async for response in proxy_dialog.start_proxy_transaction(msg, timeout=timeout):
            yield response

        proxy_dialog._maybe_close(msg)

    def _bookkeeping(self, msg, call_id):
        if msg.method not in ('REGISTER', 'SUBSCRIBE'):
            return

        expires = int(msg.headers.get('Expires', 0))

        if msg.method == 'REGISTER' and expires:
            self.registered[msg.contact_details['uri']['user']] = {
                'expires': time.time() + expires,
                'dialog': call_id
            }
        elif msg.method == 'SUBSCRIBE' and expires:
            self.subscriber[msg.contact_details['uri']['user']][msg.to_details['uri']['user']] = {
                'expires': time.time() + expires,
                'dialog': call_id
            }
        if msg.method == 'REGISTER' and not expires:
            try:
                del self.registered[msg.contact_details['uri']['user']]
            except KeyError:
                pass
        elif msg.method == 'SUBSCRIBE' and not expires:
            try:
                del self.subscriber[msg.contact_details['uri']['user']][msg.to_details['uri']['user']]
            except KeyError:
                pass

    def proxy_response(self, msg):
        msg.headers['Via'].pop(0)
        return self.send_message(msg)

    def _close_dialog(self, call_id):
        try:
            del self._dialogs[call_id]
        except KeyError:
            pass

        to_del = list()
        for user, value in self.registered.items():
            if value['dialog'] == call_id:
                to_del.append(user)
        for user in to_del:
            del self.registered[user]

        to_del = list()
        for user, subscriptions in self.subscriber.items():
            for subscribe, values in subscriptions.items():
                if values['dialog'] == call_id:
                    to_del.append((user, subscribe))

        for v in to_del:
            del self.subscriber[v[0]][v[1]]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

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

    @property
    def local_addr(self):
        if self._protocol:
            return self._protocol.transport.get_extra_info('sockname')
        else:
            return None, None

    @property
    def contacts(self):
        for contact in self.registered:
            yield contact
        for contact in self.subscriber:
            yield contact

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

    async def create_server(self, local_addr, sock):
        return await self._create_server(local_addr, sock)

    async def create_peer(self, peer_addr, local_addr=None):
        try:
            if not local_addr:
                peer = [peer for key, peer in self._peers.items() if key[0] == peer_addr][0]
            else:
                peer = self._peers[(peer_addr, local_addr)]
        except (KeyError, IndexError):
            peer = self._create_peer(peer_addr)
            await self._connect_peer(peer, local_addr)
            LOG.debug('Creating: %s', peer)
            return peer
        else:
            await peer.connected
            return peer

    def _create_peer(self, peer_addr):
        peer = Peer(peer_addr, self._app, self, loop=self._loop)
        self._peers[(peer_addr, None)] = peer
        return peer

    async def _connect_peer(self, peer, local_addr):
        peer._connected(await self._create_connection(peer_addr=peer.peer_addr, local_addr=local_addr))
        if (peer.peer_addr, None) in self._peers:
            del self._peers[(peer.peer_addr, None)]
        if (peer.peer_addr, peer.local_addr) not in self._peers:
            self._peers[(peer.peer_addr, peer.local_addr)] = peer

    async def get_peer(self, protocol, peer_addr):
        return await self._dispatch(protocol, peer_addr)

    def connection_lost(self, protocol):
        peer_addr = protocol.transport.get_extra_info('peername')
        local_addr = protocol.transport.get_extra_info('sockname')
        peer = self._peers.pop((peer_addr, local_addr), None)
        if peer:
            peer.close()

    def close(self):
        for peer in self._peers.values():
            peer.close()

    def _release(self, peer_addr, protocol, should_close=False):
        _protocol = self._protocols.pop(peer_addr, None)
        if _protocol:
            assert _protocol == protocol
            if should_close:
                protocol.transport.close()

    async def _create_server(self, local_addr, sock):
        raise NotImplementedError()

    async def _create_connection(self, peer_addr, local_addr):
        raise NotImplementedError()

    async def _dispatch(self, protocol, peer_addr):
        raise NotImplementedError()


class TCPConnector(BaseConnector):
    async def _create_server(self, local_addr, sock):
        server = await self._loop.create_server(
            lambda: TCP(app=self._app, loop=self._loop),
            host=local_addr[0],
            port=local_addr[1],
            sock=sock)
        self._servers[local_addr] = server
        return server

    async def _create_connection(self, peer_addr, local_addr):
        try:
            return self._protocols[(peer_addr, local_addr)]
        except KeyError:
            transport, proto = await self._loop.create_connection(
                lambda: TCP(app=self._app, loop=self._loop),
                host=peer_addr[0],
                port=peer_addr[1])
            local_addr = transport.get_extra_info('sockname')
            self._protocols[(peer_addr, local_addr)] = proto
            return proto

    async def _dispatch(self, protocol, _):
        peer_addr = protocol.transport.get_extra_info('peername')
        local_addr = protocol.transport.get_extra_info('sockname')
        if (peer_addr, local_addr) not in self._protocols:
            self._protocols[(peer_addr, local_addr)] = protocol
        return await self.create_peer(peer_addr, local_addr)


class UDPConnector(BaseConnector):
    async def _create_connection(self, peer_addr, local_addr):
        try:
            return self._protocols[(peer_addr, local_addr)]
        except KeyError:
            transport, proto = await self._loop.create_datagram_endpoint(
                lambda: UDP(app=self._app, loop=self._loop),
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
            _, proto = await self._loop.create_datagram_endpoint(
                lambda: UDP(app=self._app, loop=self._loop),
                sock=sock,
                local_addr=local_addr
            )
            proto_addr = proto.transport.get_extra_info('sockname')
            if sock:
                assert sock.getsockname() == proto_addr
            else:
                assert local_addr == proto_addr
            self._servers[local_addr] = proto
            return proto

    async def _dispatch(self, protocol, peer_addr):
        local_addr = protocol.transport.get_extra_info('sockname')
        if (peer_addr, local_addr) not in self._protocols:
            self._protocols[(peer_addr, local_addr)] = protocol
        return await self.create_peer(peer_addr, local_addr)
