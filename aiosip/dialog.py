import asyncio
import logging

from collections import defaultdict
from multidict import CIMultiDict

from . import utils, __version__
from .contact import Contact
from .message import Request, Response
from .dialplan import Router
from .transaction import UnreliableTransaction
from .auth import Auth

from functools import partial


LOG = logging.getLogger(__name__)


class Dialog:
    def __init__(self,
                 app,
                 from_uri,
                 to_uri,
                 call_id,
                 connection,
                 *,
                 contact_uri=None,
                 password=None,
                 router=Router(),
                 cseq=0):

        self.app = app
        self.from_uri = from_uri
        self.to_uri = to_uri
        self.from_details = Contact.from_header(from_uri)
        self.to_details = Contact.from_header(to_uri)
        self.contact_details = Contact.from_header(contact_uri or from_uri)
        self.call_id = call_id
        self.connection = connection
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
                response = Response.from_request(
                    request=msg,
                    status_code=500,
                    status_message='Server Internal Error'
                )
                self.reply(response)
        else:
            response = Response.from_request(
                request=msg,
                status_code=501,
                status_message='Not Implemented',
            )
            self.reply(response)

    async def _call_route(self, msg):
        route = self.router[msg.method]
        for middleware_factory in reversed(self.app._middleware):
            route = await middleware_factory(route)

        await route(self, msg)

    def unauthorized(self, msg):
        self._nonce = utils.gen_str(10)
        hdrs = CIMultiDict()
        hdrs['WWW-Authenticate'] = str(Auth(nonce=self._nonce, algorithm='md5', realm='sip'))
        response = Response.from_request(
            request=msg,
            status_code=401,
            status_message='Unauthorized',
            headers=hdrs
        )
        self.reply(response)

    def validate_auth(self, msg, password):
        if msg.auth and msg.auth.validate(password, self._nonce):
            self._nonce = None
            return True
        elif msg.method == 'CANCEL':
            return True
        else:
            return False

    def send(self, method, to_details=None, from_details=None, contact_details=None, headers=None, content_type=None, payload=None, future=None):

        if headers is None:
            headers = CIMultiDict()
        if 'Call-ID' not in headers:
            headers['Call-ID'] = self.call_id
        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.app.user_agent

        if from_details:
            from_details = Contact(from_details)
        else:
            from_details = self.from_details
        from_details.add_tag()

        self.cseq += 1
        msg = Request(method=method,
                      from_details=from_details,
                      to_details=to_details if to_details else self.to_details,
                      contact_details=contact_details if contact_details else self.contact_details,
                      cseq=self.cseq,
                      headers=headers,
                      content_type=content_type,
                      payload=payload,
                      future=future)

        if method != 'ACK':
            return self.start_transaction(method, msg, future=future)

        self.connection.send_message(msg)
        return None

    def start_transaction(self, method, msg, *, future=None):
        transaction = UnreliableTransaction(self, original_msg=msg,
                                            future=msg.future,
                                            loop=self.app.loop)

        self._transactions[method][self.cseq] = transaction
        return transaction.start()

    def reply(self, response):
        response.to_details.add_tag()
        response.headers['Call-ID'] = self.call_id

        if 'User-Agent' not in response.headers:
            response.headers['User-Agent'] = self.app.user_agent

        self.connection.send_message(response)

    def close(self):
        self.connection._stop_dialog(self.call_id)
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
