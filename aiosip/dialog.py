import asyncio
import logging

from collections import defaultdict
from multidict import CIMultiDict

from . import utils
from .message import Request, Response
from .dialplan import Router
from .transaction import UnreliableTransaction, ProxyTransaction, QueueTransaction
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
        self._closing = None

    async def receive_message(self, msg):
        if self._closing:
            self._closing.cancel()

        if self.cseq < msg.cseq:
            self.cseq = msg.cseq

        if isinstance(msg, Response) or msg.method == 'ACK':
            return self._receive_response(msg)
        else:
            return await self._receive_request(msg)

    def _receive_response(self, msg):
        try:
            transaction = self.transactions[msg.method][msg.cseq]
            transaction._incoming(msg)
        except KeyError:
            LOG.debug('Response without Request. The Transaction may already be closed. \n%s', msg)

    async def _receive_request(self, msg):
        self.peer._bookkeeping(msg, self.call_id)

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
                await self.reply(msg, status_code=500)
        else:
            await self.reply(msg, status_code=501)

        self._maybe_close(msg)

    async def _call_route(self, route, msg):
        for middleware_factory in reversed(self.app._middleware):
            route = await middleware_factory(route)

        await route(self, msg)

    async def unauthorized(self, msg):
        self._nonce = utils.gen_str(10)
        headers = CIMultiDict()
        headers['WWW-Authenticate'] = str(Auth(nonce=self._nonce, algorithm='md5', realm='sip'))
        await self.reply(msg, status_code=401, headers=headers)

    def validate_auth(self, msg, password):
        if msg.auth and msg.auth.validate(password, self._nonce):
            self._nonce = None
            return True
        elif msg.method == 'CANCEL':
            return True
        else:
            return False

    async def start_unreliable_transaction(self, msg, method=None):
        transaction = UnreliableTransaction(self, original_msg=msg, loop=self.app.loop)
        self.transactions[method or msg.method][msg.cseq] = transaction
        return await transaction.start()

    async def start_queue_transaction(self, msg):
        transaction = QueueTransaction(self, original_msg=msg, loop=self.app.loop)
        self.transactions[msg.method][msg.cseq] = transaction
        async for response in transaction.start():
            yield response

    async def start_proxy_transaction(self, msg, timeout=5):
        if msg.cseq not in self.transactions[msg.method]:
            transaction = ProxyTransaction(dialog=self, original_msg=msg, loop=self.app.loop, timeout=timeout)
            self.transactions[msg.method][msg.cseq] = transaction
            async for response in transaction.start():
                yield response
        else:
            LOG.debug('Message already transmitted: %s %s, %s', msg.cseq, msg.method, msg.headers['Call-ID'])
            self.transactions[msg.method][msg.cseq].retransmit()
        return

    def end_transaction(self, transaction):
        to_delete = list()
        for method, values in self.transactions.items():
            for cseq, t in values.items():
                if transaction is t:
                    transaction.close()
                    to_delete.append((method, cseq))

        for item in to_delete:
            del self.transactions[item[0]][item[1]]

    async def send(self, msg, as_request=False):
        # This allow to send string as SIP message. msg only need an encode method.

        if issubclass(Request, msg) and msg.method != 'ACK':
            return await self.start_unreliable_transaction(msg)
        elif isinstance(Response, msg) or msg.method == 'ACK':
            self.peer.send_message(msg)
            return
        elif as_request:
            return await self.start_unreliable_transaction(msg)
        else:
            self.peer.send_message(msg)
            return

    async def reply(self, request, status_code, status_message=None, payload=None, headers=None, contact_details=None,
                    wait_for_ack=False):
        msg = self._prepare_response(request, status_code, status_message, payload, headers, contact_details)
        if wait_for_ack:
            return await self.start_unreliable_transaction(msg, method='ACK')
        else:
            self.peer.send_message(msg)

    def _prepare_response(self, request, status_code, status_message=None, payload=None, headers=None,
                          contact_details=None):
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
            from_details=request.from_details,
            to_details=request.to_details,
            contact_details=self.contact_details,
            payload=payload,
            cseq=request.cseq,
            method=request.method
        )
        return msg

    async def request(self, method, contact_details=None, headers=None, payload=None):
        msg = self._prepare_request(method, contact_details, headers, payload)
        if msg.method != 'ACK':
            return await self.start_unreliable_transaction(msg)
        else:
            self.peer.send_message(msg)

    async def request_all(self, method, contact_details=None, headers=None, payload=None):
        msg = self._prepare_request(method, contact_details, headers, payload)
        if msg.method != 'ACK':
            async for response in self.start_queue_transaction(msg):
                yield response
        else:
            self.peer.send_message(msg)

    def _prepare_request(self, method, contact_details=None, headers=None, payload=None, cseq=None, to_details=None):
        self.from_details.add_tag()
        if not cseq:
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
            cseq=cseq or self.cseq,
            from_details=self.from_details,
            to_details=to_details or self.to_details,
            contact_details=self.contact_details,
            headers=headers,
            payload=payload,
        )
        return msg

    def close(self):
        self.peer._close_dialog(self.call_id)
        self._close()

    def close_later(self, delay=None):
        if delay is None:
            delay = self.app.defaults['dialog_closing_delay']
        if self._closing:
            self._closing.cancel()
        self._closing = self.app.loop.call_later(delay, self.close)

    def _maybe_close(self, msg):
        if msg.method in ('REGISTER', 'SUBSCRIBE'):
            expire = int(msg.headers.get('Expires', 0))
            delay = int(expire * 1.1) if expire else None
            self.close_later(delay)
        elif msg.method == 'NOTIFY':
            pass
        else:
            self.close_later()

    def _close(self):
        LOG.debug('Closing: %s', self)
        for transactions in self.transactions.values():
            for transaction in transactions.values():
                transaction.close()
        for task in self._tasks:
            task.cancel()

    def _connection_lost(self):
        for transactions in self.transactions.values():
            for transaction in transactions.values():
                transaction._error(ConnectionError)
        for task in self._tasks:
            task.cancel()

    async def register(self, headers=None, expires=1800, *args, **kwargs):
        if not headers:
            headers = CIMultiDict()

        if 'Allow' not in headers:
            headers['Allow'] = 'INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, SUBSCRIBE, NOTIFY, INFO, PUBLISH'

        if 'Expires' not in headers:
            headers['Expires'] = int(expires)

        if 'Allow-Events' not in headers:
            headers['Allow-Events'] = 'talk,hold,conference,refer,check-sync'

        return await self.request('REGISTER', headers=headers, *args, **kwargs)

    async def subscribe(self, headers=None, expires=1800, *args, **kwargs):
        if not headers:
            headers = CIMultiDict()

        if 'Event' not in headers:
            headers['Event'] = 'dialog'

        if 'Accept' not in headers:
            headers['Accept'] = 'application/dialog-info+xml'

        if 'Expires' not in headers:
            headers['Expires'] = int(expires)

        return await self.request('SUBSCRIBE', headers=headers, *args, **kwargs)

    async def notify(self, *args, **kwargs):
        return await self.request('NOTIFY', *args, **kwargs)

    async def invite(self, *args, **kwargs):
        async for response in self.request_all('INVITE', *args, **kwargs):
            yield response

    def ack(self, msg, headers=None, *args, **kwargs):
        if not headers:
            headers = CIMultiDict()

        headers['Via'] = msg.headers['Via']
        ack = self._prepare_request('ACK', cseq=msg.cseq, to_details=msg.to_details, *args, **kwargs)
        self.peer.send_message(ack)

    def cancel(self, *args, **kwargs):
        cancel = self._prepare_request('CANCEL', *args, **kwargs)
        self.peer.send_message(cancel)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def __repr__(self):
        return '<{0} call_id={1}, peer={2}>'.format(self.__class__.__name__, self.call_id, self.peer)
