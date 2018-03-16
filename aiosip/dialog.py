import asyncio
import enum
import logging

from collections import defaultdict
from multidict import CIMultiDict

from . import utils
from .message import Request, Response
from .transaction import UnreliableTransaction, ProxyTransaction

from .auth import Auth


LOG = logging.getLogger(__name__)


class CallState(enum.Enum):
    Calling = enum.auto()
    Proceeding = enum.auto()
    Completed = enum.auto()
    Terminated = enum.auto()


class DialogBase:
    def __init__(self,
                 app,
                 method,
                 from_details,
                 to_details,
                 call_id,
                 peer,
                 contact_details,
                 *,
                 password=None,
                 cseq=0):

        self.app = app
        self.from_details = from_details
        self.to_details = to_details
        self.contact_details = contact_details
        self.call_id = call_id
        self.peer = peer
        self.password = password
        self.cseq = cseq
        self.transactions = defaultdict(dict)

        # TODO: Needs to be last because we need the above attributes set
        self.original_msg = self._prepare_request(method)

    def _prepare_request(self, method, contact_details=None, headers=None, payload=None, cseq=None, to_details=None):
        self.from_details.add_tag()
        if not cseq:
            self.cseq += 1

        if contact_details:
            self.contact_details = contact_details

        headers = CIMultiDict(headers or {})

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

    async def start(self, *, expires=None):
        # TODO: this is a hack
        headers = {}
        if expires:
            headers['Expires'] = expires
        return await self.request(self.original_msg.method, headers=headers)

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

    def close(self, *, fast=False):
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

    def _connection_lost(self):
        for transactions in self.transactions.values():
            for transaction in transactions.values():
                transaction._error(ConnectionError)

    async def start_unreliable_transaction(self, msg, method=None):
        transaction = UnreliableTransaction(self, original_msg=msg, loop=self.app.loop)
        self.transactions[method or msg.method][msg.cseq] = transaction
        return await transaction.start()

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

    async def request(self, method, contact_details=None, headers=None, payload=None):
        msg = self._prepare_request(method, contact_details, headers, payload)
        if msg.method != 'ACK':
            return await self.start_unreliable_transaction(msg)
        else:
            self.peer.send_message(msg)

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

        headers = CIMultiDict(headers or {})

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
        return msg

    def __repr__(self):
        return f'<{self.__class__.__name__} call_id={self.call_id}, peer={self.peer}>'

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.close()

    async def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()


class Dialog(DialogBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._nonce = None
        self._closing = None
        self._incoming = asyncio.Queue()

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

        if 'tag' in msg.from_details['params']:
            self.to_details['params']['tag'] = msg.from_details['params']['tag']

        await self._incoming.put(msg)
        self._maybe_close(msg)

    async def refresh(self, headers=None, expires=1800, *args, **kwargs):
        headers = CIMultiDict(headers or {})
        if 'Expires' not in headers:
            headers['Expires'] = int(expires)
        return await self.request(self.original_msg.method, headers=headers, *args, **kwargs)

    async def close(self, fast=False, headers=None, *args, **kwargs):
        headers = CIMultiDict(headers or {})
        if 'Expires' not in headers:
            headers['Expires'] = 0
        return await self.request(self.original_msg.method, headers=headers, *args, **kwargs)

    async def notify(self, *args, headers=None, **kwargs):
        headers = CIMultiDict(headers or {})

        if 'Event' not in headers:
            headers['Event'] = 'dialog'

        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/dialog-info+xml'

        if 'Subscription-State' not in headers:
            headers['Subscription-State'] = 'active'

        return await self.request('NOTIFY', *args, headers=headers, **kwargs)

    def cancel(self, *args, **kwargs):
        cancel = self._prepare_request('CANCEL', *args, **kwargs)
        self.peer.send_message(cancel)

    async def recv(self):
        return await self._incoming.get()


class InviteDialog(DialogBase):
    def __init__(self, *args, **kwargs):
        super().__init__(method="INVITE", *args, **kwargs)

        self._queue = asyncio.Queue()
        self._state = CallState.Calling
        self._waiter = asyncio.Future()

    async def receive_message(self, msg):  # noqa: C901
        async def set_result(msg):
            self.ack(msg)
            if not self._waiter.done():
                self._waiter.set_result(msg)
            await self._queue.put(msg)

        async def handle_calling_state(msg):
            if 100 <= msg.status_code < 200:
                self._state = CallState.Proceeding

            elif msg.status_code == 200:
                self._state = CallState.Terminated
                await set_result(msg)

            elif 300 <= msg.status_code < 700:
                self._state = CallState.Completed
                await set_result(msg)

        async def handle_proceeding_state(msg):
            if 100 <= msg.status_code < 200:
                await self._queue.put(msg)

            elif msg.status_code == 200:
                self._state = CallState.Terminated
                await set_result(msg)

            elif 300 <= msg.status_code < 700:
                self._state = CallState.Completed
                await set_result(msg)

        async def handle_completed_state(msg):
            # Any additional messages in this state MUST be acked but
            # are NOT to be passed up
            self.ack(msg)

        # TODO: sip timers and flip to Terminated after timeout
        if self._state == CallState.Calling:
            await handle_calling_state(msg)

        elif self._state == CallState.Proceeding:
            await handle_proceeding_state(msg)

        elif self._state == CallState.Completed:
            await handle_completed_state(msg)

        elif self._state == CallState.Terminated:
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

    @property
    def state(self):
        return self._state

    async def start(self, *, expires=None):
        # TODO: this is a hack
        self.peer.send_message(self.original_msg)

    async def wait_for_terminate(self):
        while not self._waiter.done():
            yield await self._queue.get()

    async def ready(self):
        msg = await self._waiter
        if msg.status_code != 200:
            raise RuntimeError("INVITE failed with {}".format(msg.status_code))

    def ack(self, msg, headers=None, *args, **kwargs):
        headers = CIMultiDict(headers or {})

        headers['Via'] = msg.headers['Via']
        ack = self._prepare_request('ACK', cseq=msg.cseq, to_details=msg.to_details, headers=headers, *args, **kwargs)
        self.peer.send_message(ack)

    def end_transaction(self, transaction):
        to_delete = list()
        for method, values in self.transactions.items():
            for cseq, t in values.items():
                if transaction is t:
                    transaction.close()
                    to_delete.append((method, cseq))

        for item in to_delete:
            del self.transactions[item[0]][item[1]]

    async def close(self):
        msg = self._prepare_request('BYE')
        transaction = UnreliableTransaction(self, original_msg=msg, loop=self.app.loop)
        self.transactions[msg.method][msg.cseq] = transaction
        return await transaction.start()

    def _close(self):
        pass
