import asyncio
import logging
import uuid

from .dialplan import Router
from .protocol import UDP, TCP
from .contact import Contact

LOG = logging.getLogger(__name__)


class Peer:
    def __init__(self, peer_addr, app, connector, key, protocol, *, loop=None):
        self.peer_addr = peer_addr
        self._app = app
        self._connector = connector
        self._key = key
        self._protocol = protocol
        self._loop = loop
        self._dialogs = {}

    def close(self):
        for dialog in self._dialogs.values():
            dialog._close()

        if self._protocol is not None:
            LOG.debug('Closing connection for %s', self.peer_addr)
            self._connector._release(self._key, self._protocol, should_close=True)
            self._protocol = None

    def send_message(self, msg):
        self._protocol.send_message(msg, addr=self.peer_addr)

    def create_dialog(self, from_details, to_details, contact_details=None, password=None, call_id=None, cseq=0, router=Router()):
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

        self._dialogs[call_id] = dialog
        return dialog

    def _stop_dialog(self, call_id):
        try:
            del self._dialogs[call_id]
        except KeyError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def local_addr(self):
        return self._protocol.transport.get_extra_info('sockname')

    def __repr__(self):
        return '<{0} {1[0]}:{1[1]}, local_addr={2[0]}:{2[1]}>'.format(
            self.__class__.__name__, self.peer_addr, self.local_addr)


class BaseConnector:
    def __init__(self, app, *, loop=None):
        self._app = app
        self._loop = loop or asyncio.get_event_loop()

        self._protocols = {}
        self._peers = {}
        self._servers = []

    async def create_server(self, local_addr, sock):
        return await self._create_server(local_addr, sock)

    async def create_peer(self, local_addr, peer_addr):
        key = local_addr, peer_addr
        try:
            return self._peers[key]
        except KeyError:
            LOG.debug('New connection for %s', peer_addr)
            protocol = await self._create_connection(local_addr, peer_addr)
            return self._create_peer(peer_addr, protocol, key)

    def _create_peer(self, peer_addr, protocol, key):
        peer = Peer(peer_addr, self._app, self, key, protocol, loop=self._loop)
        self._peers[key] = peer
        return peer

    async def get_peer(self, protocol, peer_addr):
        return await self._dispatch(protocol, peer_addr)

    def connection_lost(self, protocol):
        key = self._make_key(protocol)
        peer = self._peers.pop(key, None)
        if peer:
            peer.close()

    def close(self):
        for peer in self._peers.values():
            peer.close()

    def _release(self, key, protocol, should_close=False):
        _protocol = self._protocols.pop(key, None)
        if _protocol:
            assert _protocol == protocol
            if should_close:
                protocol.transport.close()

    async def _make_key(self, protocol):
        raise NotImplementedError()

    async def _create_server(self, local_addr, sock):
        raise NotImplementedError()

    async def _create_connection(self, peer_addr):
        raise NotImplementedError()

    async def _dispatch(self, protocol, peer_addr):
        raise NotImplementedError()


class TCPConnector(BaseConnector):
    def _make_key(self, protocol):
        local_addr = protocol.transport.get_extra_info('sockname')
        peer_addr = protocol.transport.get_extra_info('peername')
        return local_addr, peer_addr

    def _create_server(self, local_addr, sock):

        if local_addr:
            return self._loop.create_server(
                lambda: TCP(app=self._app, loop=self._loop),
                host=local_addr[0],
                port=local_addr[1])
        else:
            return self._loop.create_server(
                lambda: TCP(app=self._app, loop=self._loop),
                sock=sock)

    async def _create_connection(self, local_addr, peer_addr):
        try:
            return self._protocols[(local_addr, peer_addr)]
        except KeyError:
            _, proto = await self._loop.create_connection(
                lambda: TCP(app=self._app, loop=self._loop),
                local_addr=local_addr,
                host=peer_addr[0],
                port=peer_addr[1])
            self._protocols[(local_addr, peer_addr)] = proto
            return proto

    async def _dispatch(self, protocol, addr):
        key = self._make_key(protocol)
        if key not in self._protocols:
            self._protocols[key] = protocol

        try:
            return self._peers[key]
        except KeyError:
            peer_addr = key[1]
            LOG.debug('New connection for %s', peer_addr)
            return self._create_peer(peer_addr, protocol, key)


class UDPConnector(BaseConnector):
    def _make_key(self, protocol):
        return protocol.transport.get_extra_info('sockname')

    def _create_server(self, local_addr, sock):
        return self._create_connection(local_addr, None, sock=sock)

    async def _create_connection(self, local_addr, peer_addr, sock=None):
        try:
            return self._protocols[local_addr]
        except KeyError:
            _, proto = await self._loop.create_datagram_endpoint(
                lambda: UDP(app=self._app, loop=self._loop),
                local_addr=local_addr)
            self._protocols[local_addr] = proto
            return proto

    async def _dispatch(self, protocol, peer_addr):
        local_addr = protocol.transport.get_extra_info('sockname')
        peer = await self.create_peer(local_addr, peer_addr)
        assert peer._protocol == protocol
        return peer

