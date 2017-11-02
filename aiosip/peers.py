import asyncio
import logging
import uuid

from . import utils
from .dialplan import Router, ProxyRouter
from .protocol import UDP, TCP
from .contact import Contact

LOG = logging.getLogger(__name__)


class Peer:
    def __init__(self, peer_addr, app, connector, *, loop=None):
        self.peer_addr = peer_addr
        self.registered = {}
        self.subscriber = {}
        self._app = app
        self._connector = connector
        self._protocol = None
        self._loop = loop
        self._dialogs = {}
        self._connected_future = asyncio.Future(loop=loop)
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
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
                      router=Router()):
        if not call_id:
            call_id = str(uuid.uuid4())
        LOG.debug('Creating dialog %s for peer %s', call_id, self)

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

    async def proxy_request(self, dialog, msg):
        proxy_dialog = self._dialogs.get(dialog.call_id)
        if not proxy_dialog:
            proxy_dialog = self.create_dialog(
                from_details=dialog.from_details,
                to_details=dialog.to_details,
                call_id=dialog.call_id,
                router=self._app.dialplan.get_user(dialog.to_details['uri']['user']) or ProxyRouter()
            )

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

        if msg.method != 'ACK':
            async for response in proxy_dialog.start_proxy_transaction(msg, dialog.peer):
                yield response
        else:
            self.send_message(msg)
            return

    def proxy_response(self, msg):
        msg.headers['Via'].pop(0)
        return self.send_message(msg)

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
        for contact, expire in self.registered.items():
            yield contact, expire
        for contact, expire in self.subscriber.items():
            yield contact, expire

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

    async def create_peer(self, peer_addr):
        try:
            peer = self._peers[peer_addr]
            await peer.connected
            return peer
        except KeyError:
            peer = self._create_peer(peer_addr)
            peer._connected(await self._create_connection(peer_addr=peer_addr))
            return peer

    def _create_peer(self, peer_addr):
        peer = Peer(peer_addr, self._app, self, loop=self._loop)
        self._peers[peer_addr] = peer
        LOG.debug('New peer: %s for %s', peer, self.__class__.__name__)
        return peer

    async def get_peer(self, protocol, peer_addr):
        return await self._dispatch(protocol, peer_addr)

    def connection_lost(self, protocol):
        peer_addr = protocol.transport.get_extra_info('peername')
        peer = self._peers.pop(peer_addr, None)
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

    async def _create_connection(self, peer_addr):
        raise NotImplementedError()

    async def _dispatch(self, protocol, peer_addr):
        raise NotImplementedError()


class TCPConnector(BaseConnector):
    def _create_server(self, local_addr, sock):
        return self._loop.create_server(
            lambda: TCP(app=self._app, loop=self._loop),
            host=local_addr[0],
            port=local_addr[1],
            sock=sock)

    async def _create_connection(self, peer_addr):
        try:
            return self._protocols[peer_addr]
        except KeyError:
            transport, proto = await self._loop.create_connection(
                lambda: TCP(app=self._app, loop=self._loop),
                host=peer_addr[0],
                port=peer_addr[1])
            self._protocols[peer_addr] = proto
            return proto

    async def _dispatch(self, protocol, addr):
        peer_addr = protocol.transport.get_extra_info('peername')
        if peer_addr not in self._protocols:
            self._protocols[peer_addr] = protocol
        return await self.create_peer(peer_addr)


class UDPConnector(BaseConnector):
    def _create_server(self, local_addr, sock):
        return self._create_connection(local_addr=local_addr, sock=sock)

    async def _create_connection(self, peer_addr=None, local_addr=None, sock=None):
        if not peer_addr and not local_addr and not sock:
            raise ValueError('One of peer_addr, local_addr, sock is mandatory')
        elif sock:
            local_addr = sock.getsockname()

        try:
            if local_addr:
                return self._protocols[local_addr]
            else:
                return list(self._protocols.values())[0]  # In UDP we only need one connection
        except (KeyError, IndexError):
            if sock:
                _, proto = await self._loop.create_datagram_endpoint(
                    lambda: UDP(app=self._app, loop=self._loop),
                    sock=sock
                )
            elif local_addr:
                _, proto = await self._loop.create_datagram_endpoint(
                    lambda: UDP(app=self._app, loop=self._loop),
                    local_addr=local_addr)
                assert local_addr == proto.transport.get_extra_info('sockname')
            else:
                _, proto = await self._loop.create_datagram_endpoint(
                    lambda: UDP(app=self._app, loop=self._loop),
                    remote_addr=peer_addr)
                local_addr = proto.transport.get_extra_info('sockname')
            self._protocols[local_addr] = proto
            return proto

    async def _dispatch(self, protocol, peer_addr):
        return await self.create_peer(peer_addr)
