import uuid
import asyncio
import logging

from . import exceptions, utils
from .protocol import UDP
from .dialog import Dialog as OldDialog
from .contact import Contact
from .peers import UDPConnector
from .message import Response

LOG = logging.getLogger(__name__)


class Peer:
    def __init__(self, host, port, protocol=UDP, local_addr=None):
        self._addr = (host, port)
        self._proto_type = protocol
        self._protocol = None
        self._dialogs = dict()
        self._connected = False
        self._disconected = asyncio.Future()
        self._local_addr = local_addr

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
            response = await dialog.start(timeout=timeout)
            dialog.response = response
            dialog.status_code = response.status_code
            dialog.status_message = response.status_message
            return dialog
        except asyncio.CancelledError:
            dialog.cancel()
            raise
        except exceptions.AuthentificationFailed:
            await dialog.close(fast=True)
            raise

    async def register(self, *args, **kwargs):
        dialog = await self.request('REGISTER', *args, **kwargs)
        return dialog

    async def connect(self):
        connector = UDPConnector()
        self._protocol = await connector._create_connection(peer=self, peer_addr=self._addr, local_addr=self._local_addr)

    def _connection_lost(self, protocol):
        self._disconected.set_result(True)

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
        # LOG.error("Finding route for %s", msg)
        pass

    def send_message(self, msg):
        self._protocol.send_message(msg, addr=self._addr)

    async def close(self):
        self._protocol.transport.close()
        await self._disconected

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
