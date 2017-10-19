import asyncio
import logging

from collections import defaultdict
from multidict import CIMultiDict

from . import utils, __version__
from .message import Request, Response
from .dialplan import Router
from .transaction import UnreliableTransaction
from .auth import Auth

from functools import partial


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
                 router=Router(),
                 cseq=0):

        self.app = app
        self.from_details = from_details
        self.to_details = to_details
        self.contact_details = contact_details
        self.call_id = call_id
        self.peer = peer
        self.password = password
        self.cseq = cseq
        self.router = router
        self._transactions = defaultdict(dict)
        self.callbacks = defaultdict(list)
        self._tasks = list()
        self._nonce = None

    def register_callback(self, method, callback, *args, **kwargs):
        self.router[method.lower()] = partial(callback, *args, **kwargs)

    def unregister_callback(self, method):
        del self.router[method.lower()]

    async def receive_message(self, msg):
        if self.cseq < msg.cseq:
            self.cseq = msg.cseq

        if isinstance(msg, Response):
            try:
                transaction = self._transactions[msg.method][msg.cseq]
                transaction.feed_message(msg)
            except KeyError:
                raise ValueError('This Response SIP message doesn\'t have Request: "%s"' % msg)

        elif msg.method in self.router:
            try:
                t = asyncio.ensure_future(self._call_route(msg))
                self._tasks.append(t)
                await t
            except asyncio.CancelledError:
                pass
            except Exception as e:
                LOG.exception(e)
                self.reply(msg, status_code=500)
        else:
            self.reply(msg, status_code=501)

    async def _call_route(self, msg):
        route = self.router[msg.method]
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
        transaction = UnreliableTransaction(self, original_msg=msg,
                                            future=msg.future,
                                            loop=self.app.loop)

        self._transactions[msg.method][self.cseq] = transaction
        return await transaction.start()

    async def send(self, msg):

        if issubclass(Request, msg):
            return await self._send_request(msg)
        elif isinstance(Response, msg):
            return self.peer.send_message(msg)
        else:
            return self.peer.send_message(msg)

    async def _send_request(self, msg):

        if msg.method != 'ACK':
            return await self.start_transaction(msg)

        self.peer.send_message(msg)
        return None

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
        return await self._send_request(msg)

    def close(self):
        self.peer._stop_dialog(self.call_id)
        self._close()

    def _close(self):
        LOG.debug('Closing dialog: %s', self.call_id)
        for transactions in self._transactions.values():
            for transaction in transactions.values():
                # transaction.cancel()
                if not transaction.future.done():
                    transaction.future.set_exception(ConnectionAbortedError)
        for task in self._tasks:
            task.cancel()

    def _connection_lost(self):
        for transactions in self._transactions.values():
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
