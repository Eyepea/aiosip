import uuid
import asyncio
import logging

from copy import deepcopy
from async_timeout import timeout
from collections import MutableMapping
from contextlib import asynccontextmanager

from . import exceptions, utils
from .protocol import UDP, TCP
from .dialog import Dialog as Dialog
from .contact import Contact
from .peers import UDPConnector, TCPConnector
from .message import Response, Request

LOG = logging.getLogger(__name__)

CONNECTOR = {
    UDP: UDPConnector,
    TCP: TCPConnector
}


class Peer(MutableMapping):
    def __init__(self, host, port, protocol=UDP, local_addr=None):
        self._addr = (host, port)
        self._proto_type = protocol
        self._protocol = None
        self._dialogs = dict()
        self._connected = False
        self._disconected = asyncio.Future()
        self._local_addr = local_addr
        self._routes = dict()
        self._state = dict()

    def add_route(self, method, callback):
        self._routes[method.lower()] = callback

    def send_message(self, msg):
        self._protocol.send_message(msg, addr=self._addr)

    async def connect(self, **kwargs):
        connector = CONNECTOR[self._proto_type]()
        self._protocol, self._addr, self._local_addr = await connector._create_connection(
            peer=self,
            peer_addr=self._addr,
            local_addr=self._local_addr,
            **kwargs
        )

    def _create_dialog(self, method, from_details, to_details, contact_details=None, password=None, call_id=None,
                       headers=None, payload=None, cseq=0, inbound=False, dialog_factory=Dialog, **kwargs):

        from_details.add_tag()

        if not call_id:
            call_id = str(uuid.uuid4())

        if not contact_details:
            host, port = self._addr

            # No way to get the public local addr in UDP. Allow an override or select the From host
            # Maybe with https://bugs.python.org/issue31203
            # if self._app.defaults['override_contact_host']:
            #     host = self._app.defaults['override_contact_host']
            # elif host == '0.0.0.0' or host.startswith('127.'):
            #     host = from_details['uri']['host']

            contact_details = Contact(
                {
                    'uri': 'sip:{username}@{host_and_port};transport={protocol}'.format(
                        username=from_details['uri']['user'],
                        host_and_port=utils.format_host_and_port(host, port),
                        protocol=self._proto_type.__name__.lower()
                    )
                }
            )

        dialog = dialog_factory(
            method=method,
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

        self._dialogs[dialog.dialog_id] = dialog
        self._dialogs[frozenset((dialog.original_msg.to_details['params'].get('tag'), None, dialog.call_id))] = dialog
        return dialog

    async def request(self, method, from_details, to_details, contact_details=None, password=None, call_id=None,
                      headers=None, cseq=0, payload=None, dialog_factory=Dialog, timeout=None, **kwargs):

        if not self._protocol:
            await self.connect()

        dialog = self._create_dialog(method=method,
                                     from_details=from_details,
                                     to_details=to_details,
                                     contact_details=contact_details,
                                     headers=headers,
                                     payload=payload,
                                     password=password,
                                     call_id=call_id,
                                     cseq=cseq,
                                     dialog_factory=dialog_factory,
                                     **kwargs)

        try:
            await dialog.start(timeout=timeout)
            return dialog
        except asyncio.CancelledError:
            dialog.cancel()
            raise
        except exceptions.AuthentificationFailed:
            await dialog.close(fast=True)
            raise

    @asynccontextmanager
    async def register(self, to_details, from_details, expires=120, headers=None, **kwargs):
        if headers:
            headers["Expires"] = expires
        else:
            headers = {"Expires": expires}

        cseq = 1
        call_id = str(uuid.uuid4())

        dialog = await self.request(
            method='REGISTER',
            headers=deepcopy(headers),
            call_id=call_id,
            cseq=cseq,
            to_details=deepcopy(to_details),
            from_details=deepcopy(from_details),
            **kwargs,
        )
        async for message in dialog:
            if isinstance(message, Response) and message.status_code == 200:
                expires = int(message.headers["Expires"])
                cseq = message.cseq
                break
            else:
                await dialog.close()
                raise exceptions.RegisterFailed(message)

        await dialog.close()
        registration = asyncio.create_task(self._keep_registration(expires=expires, headers=headers, to_details=to_details, from_details=from_details, cseq=cseq, call_id=call_id, **kwargs))

        yield

        registration.cancel()
        await registration

    async def _keep_registration(self, expires, headers, to_details, from_details, cseq, call_id, **kwargs):
        try:
            await asyncio.sleep(expires)
            while True:
                dialog = await self.request(
                    method='REGISTER',
                    headers=deepcopy(headers),
                    call_id=call_id,
                    cseq=cseq,
                    to_details=deepcopy(to_details),
                    from_details=deepcopy(from_details),
                    **kwargs,
                )
                async for message in dialog:
                    if isinstance(message, Response) and message.status_code == 200:
                        expires = int(message.headers["Expires"])
                        cseq = message.cseq
                        break
                    else:
                        raise exceptions.RegisterFailed(message)

                await dialog.close()
                await asyncio.sleep(expires / 2)

        except asyncio.CancelledError:
            async with timeout(10):
                headers["Expires"] = 0
                dialog = await self.request(
                    method='REGISTER',
                    headers=deepcopy(headers),
                    call_id=call_id,
                    cseq=cseq,
                    to_details=deepcopy(to_details),
                    from_details=deepcopy(from_details),
                    **kwargs,
                )
                async for message in dialog:
                    if isinstance(message, Response) and message.status_code == 200:
                        break
            await dialog.close()
        except Exception:
            LOG.error("Unable to maintain registration for peer: %s", self)

    @asynccontextmanager
    async def subscribe(self, *args, expires=120, headers=None, **kwargs):
        if headers:
            headers["Expires"] = expires
        else:
            headers = {"Expires": expires}

        dialog = await self.request('SUBSCRIBE', *args, headers=headers, **kwargs)
        async for message in dialog:
            if isinstance(message, Response) and message.status_code == 200:
                expires = int(message.headers["Expires"])
                break
            else:
                raise exceptions.SubscriptionFailed(message)

        subscription = asyncio.create_task(self._keep_subscription(dialog, expires=expires, headers=headers))

        yield dialog

        subscription.cancel()
        await subscription

    async def _keep_subscription(self, dialog, expires, headers):
        try:
            await asyncio.sleep(expires)
            while True:
                response = await dialog.request("SUBSCRIBE", headers=headers)
                if response.status_code != 200:
                    raise exceptions.SubscriptionFailed(response)
                expires = int(response.headers["Expires"])
                await asyncio.sleep(expires / 2)
        except asyncio.CancelledError:
            async with timeout(10):
                headers["Expires"] = 0
                await dialog.request("SUBSCRIBE", headers=headers)
        except Exception:
            LOG.error("Unable to maintain subscription for peer: %s", self)

    async def invite(self, *args, sdp=None, headers=None, payload=None, **kwargs):
        if sdp and payload:
            raise TypeError("Only one of 'sdp', 'payload' should be set")
        elif sdp:
            payload = sdp
            if headers:
                headers["Content-Type"] = "application/sdp"
            else:
                headers = {"Content-Type": "application/sdp"}

        dialog = await self.request('INVITE', *args, headers=headers, payload=payload, **kwargs)
        try:
            async for message in dialog:
                message.dialog = dialog
                if isinstance(message, Response) and message.status_code == 200:
                    dialog.ack(message)
                    yield message
                elif isinstance(message, Request) and message.method.upper() in ('BYE', 'CANCEL'):
                    await dialog.reply(message, status_code=200)
                    yield message
                    return
                else:
                    yield message
        finally:
            await dialog.close()

    #########
    # Utils #
    #########
    def generate_via_headers(self, branch=utils.gen_branch()):
        return f'SIP/2.0/{self._protocol.via} {self._local_addr[0]}:{self._local_addr[1]};branch={branch}'

    #####################
    # Incoming Messages #
    #####################
    async def _dispatch(self, protocol, msg, addr):
        call_id = msg.headers['Call-ID']
        dialog = None

        # First incoming request of dialogs do not yet have a tag in to headers
        if 'tag' in msg.to_details['params']:
            dialog = self._dialogs.get(frozenset((msg.to_details['params']['tag'],
                                                  msg.from_details['params']['tag'],
                                                  call_id)))

        # First response of dialogs have a tag in the to header but the dialog is not
        # yet aware of it. Try to match only with the from header tag
        if dialog is None:
            dialog = self._dialogs.get(frozenset((None, msg.from_details['params']['tag'], call_id)))

        if dialog is not None:
            await dialog.receive_message(msg)
            return

        # If we got an ACK, but nowhere to deliver it, drop it. If we
        # got a response without an associated message (likely a stale
        # retransmission, drop it)
        if isinstance(msg, Response) or msg.method == 'ACK':
            LOG.debug('Discarding incoming message: %s', msg)
            return

        await self._find_route(protocol, msg)

    async def _find_route(self, protocol, msg):

        dialog = self._create_dialog(
            method=msg.method,
            from_details=Contact.from_header(msg.headers["To"]),
            to_details=Contact.from_header(msg.headers["From"]),
            call_id=msg.headers["Call-ID"],
            inbound=True)

        dialog.original_msg = msg

        route = self._routes.get(msg.method.lower())
        if route:
            await route(dialog)
        else:
            await dialog.reply(msg, status_code=501)
            await dialog.close()

    def _connection_lost(self, protocol):
        self._disconected.set_result(True)

    ###################
    # Context Manager #
    ###################
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._protocol:
            self._protocol.transport.close()
            await self._disconected

    ######################
    # MutableMapping API #
    ######################
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
