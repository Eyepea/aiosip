import asyncio
import logging
import time

from collections import defaultdict
from multidict import CIMultiDict

from . import utils
from .message import Request, Response
from .dialplan import Router
from .transaction import UnreliableTransaction, ProxyTransaction
from .auth import Auth


LOG = logging.getLogger(__name__)


class Dialog:
    def __init__(self,
                 app,
                 from_details,
                 to_details,
                 call_id,
                 peer,
                 contact_details,
                 *,
                 password=None,
                 router=None,
                 cseq=0):

        self.app = app
        self.from_details = from_details
        self.to_details = to_details
        self.contact_details = contact_details
        self.call_id = call_id
        self.peer = peer
        self.password = password
        self.cseq = cseq
        self.router = router or Router()
        self.transactions = defaultdict(dict)
        self.callbacks = defaultdict(list)
        self._tasks = list()
        self._nonce = None

    async def receive_message(self, msg):
        if self.cseq < msg.cseq:
            self.cseq = msg.cseq

        if isinstance(msg, Response):
            return self._receive_response(msg)
        else:
            return await self._receive_request(msg)

    def _receive_response(self, msg):
        try:
            transaction = self.transactions[msg.method][msg.cseq]
            transaction._incoming(msg)
        except KeyError:
            raise ValueError('This Response SIP message doesn\'t have a Request: "%s"' % msg)

    async def _receive_request(self, msg):

        if msg.method == 'REGISTER':
            expire = int(msg.headers.get('Expires', 0))
            self.peer.registered[msg.contact_details['uri']['user']] = time.time() + expire
        elif msg.method == 'SUBSCRIBE':
            expire = int(msg.headers.get('Expires', 0))
            self.peer.subscriber[msg.contact_details['uri']['user']] = time.time() + expire

        route = self.router.get(msg.method)
        if route:
            try:
                t = asyncio.ensure_future(self._call_route(route, msg))
                self._tasks.append(t)
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                LOG.exception(e)
                self.reply(msg, status_code=500)
        else:
            self.reply(msg, status_code=501)

    async def _call_route(self, route, msg):
        for middleware_factory in reversed(self.app._middleware):
            route = await middleware_factory(route)

        await route(self, msg)

    def unauthorized(self, msg):
        self._nonce = utils.gen_str(10)
        headers = CIMultiDict()
        headers['WWW-Authenticate'] = str(Auth(nonce=self._nonce, algorithm='md5', realm='sip'))
        self.reply(msg, status_code=401, headers=headers)

    def validate_auth(self, msg, password):
        if msg.auth and msg.auth.validate(password, self._nonce):
            self._nonce = None
            return True
        elif msg.method == 'CANCEL':
            return True
        else:
            return False

    async def start_transaction(self, msg):
        transaction = UnreliableTransaction(self, original_msg=msg, loop=self.app.loop)
        self.transactions[msg.method][msg.cseq] = transaction
        async for response in transaction.start():
            yield response

    async def start_proxy_transaction(self, msg, peer):
        if msg.cseq not in self.transactions[msg.method]:
            transaction = ProxyTransaction(dialog=self, original_msg=msg, loop=self.app.loop, proxy_peer=peer)
            self.transactions[msg.method][msg.cseq] = transaction
            async for response in transaction.start():
                yield response
        else:
            LOG.debug('Message already transmitted: %s %s, %s', msg.cseq, msg.method, msg.headers['Call-ID'])
            self.transactions[msg.method][msg.cseq].retransmit()
        return

    async def send(self, msg, as_request=False):
        # This allow to send string as SIP message. msg only need an encode method.

        if issubclass(Request, msg) and msg.method != 'ACK':
            async for response in self.start_transaction(msg):
                yield response
        elif isinstance(Response, msg) or msg.method == 'ACK':
            self.peer.send_message(msg)
            return
        elif as_request:
            async for response in self.start_transaction(msg):
                yield response
        else:
            self.peer.send_message(msg)
            return

    def reply(self, request, status_code, status_message=None, payload=None, headers=None, contact_details=None):
        self.from_details.add_tag()

        if contact_details:
            self.contact_details = contact_details

        if not headers:
            headers = CIMultiDict()

        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.app.defaults['user_agent']

        headers['Call-ID'] = self.call_id
        headers['Via'] = request.headers['Via']

        msg = Response(
            status_code=status_code,
            status_message=status_message,
            headers=headers,
            from_details=self.to_details,
            to_details=self.from_details,
            contact_details=self.contact_details,
            payload=payload,
            cseq=request.cseq,
            method=request.method
        )
        self.peer.send_message(msg)

    async def request(self, method, contact_details=None, headers=None, payload=None, future=None):
        self.from_details.add_tag()
        self.cseq += 1

        if contact_details:
            self.contact_details = contact_details

        if not headers:
            headers = CIMultiDict()

        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.app.defaults['user_agent']

        headers['Call-ID'] = self.call_id

        msg = Request(
            method=method,
            cseq=self.cseq,
            from_details=self.from_details,
            to_details=self.to_details,
            contact_details=self.contact_details,
            headers=headers,
            payload=payload,
            future=future
        )
        async for response in self.start_transaction(msg):
            yield response

    def close(self):
        self.peer._stop_dialog(self.call_id)
        self._close()

    def _close(self):
        LOG.debug('Closing dialog: %s', self.call_id)
        for transactions in self.transactions.values():
            for transaction in transactions.values():
                transaction.close()
        for task in self._tasks:
            task.cancel()

    def _connection_lost(self):
        for transactions in self.transactions.values():
            for transaction in transactions.values():
                if not transaction.future.done():
                    transaction.future.set_exception(ConnectionError)
        for task in self._tasks:
            task.cancel()

    def register(self, headers=None, attempts=3, expires=360):
        if not headers:
            headers = CIMultiDict()

        if 'Allow' not in headers:
            headers['Allow'] = 'INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, SUBSCRIBE, NOTIFY, INFO, PUBLISH'

        if 'Expires' not in headers:
            headers['Expires'] = int(expires)

        if 'Allow-Events' not in headers:
            headers['Allow-Events'] = 'talk,hold,conference,refer,check-sync'

        send_msg_future = self.send(method='REGISTER',
                                    headers=headers,
                                    payload='')
        return send_msg_future

    @asyncio.coroutine
    def invite(self, headers=None, sdp=None, attempts=3):
        if not headers:
            headers = CIMultiDict()

        send_msg_future = self.send(method='INVITE',
                                    headers=headers,
                                    payload=sdp)
        return send_msg_future

    async def ack(self, msg):

        ack = Request(
            method='ACK',
            cseq=msg.cseq,
            from_details=self.from_details,
            to_details=self.to_details,
            contact_details=self.contact_details,
        )
        await self.send(ack)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self):
        return '<{0} call_id={1}, peer={2}>'.format(self.__class__.__name__, self.call_id, self.peer)
