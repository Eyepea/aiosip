import asyncio
import logging

from aiosip.auth import Auth
from .exceptions import AuthentificationFailed


LOG = logging.getLogger(__name__)


class BaseTransaction:
    def __init__(self, dialog, original_msg=None, attempts=3, *, loop=None):
        self.dialog = dialog
        self.original_msg = original_msg
        self.loop = loop or asyncio.get_event_loop()
        self.attempts = attempts
        self.retransmission = None
        self.authentification = None
        self._running = True
        LOG.debug('Creating: %s', self)

    async def start(self):
        raise NotImplementedError

    def _incoming(self, msg):
        if self.retransmission:
            self.retransmission.cancel()
            self.retransmission = None

        if self.authentification and msg.status_code not in (401, 407):
            self.authentification.cancel()
            self.authentification = None

    def _error(self, error):
        raise NotImplementedError

    def _result(self, msg):
        raise NotImplementedError

    def close(self):
        self._running = False
        LOG.debug('Closing %s', self)
        if self.retransmission:
            self.retransmission.cancel()
            self.retransmission = None

    async def _timer(self, timeout=0.5):
        max_timeout = timeout * 64
        while timeout <= max_timeout:
            self.dialog.peer.send_message(self.original_msg)
            await asyncio.sleep(timeout)
            timeout *= 2

        self._error(asyncio.TimeoutError('SIP timer expired for {cseq}, {method}, {call_id}'.format(
            cseq=self.original_msg.cseq,
            method=self.original_msg.method,
            call_id=self.original_msg.headers['Call-ID']
        )))

    def _handle_authenticate(self, msg):
        if self.dialog.password is None:
            raise ValueError('Password required for authentication')

        self.attempts -= 1
        if self.attempts < 1:
            self._error(AuthentificationFailed('Too many unauthorized attempts!'))
            return
        elif self.authentification:
            self.authentification.cancel()
            self.authentification = None

        if msg.method.upper() == 'REGISTER':
            username = msg.to_details['uri']['user']
        else:
            username = msg.from_details['uri']['user']

        self.original_msg.cseq += 1
        self.original_msg.headers['Authorization'] = msg.auth.generate_authorization(
            username=username,
            password=self.dialog.password,
            payload=msg.payload,
            uri=msg.to_details['uri'].short_uri()
        )

        self.dialog.transactions[self.original_msg.method][self.original_msg.cseq] = self
        self.authentification = asyncio.ensure_future(self._timer())

    def _handle_proxy_authenticate(self, msg):
        self._handle_proxy_authenticate(msg)
        self.original_msg = self.original_msg.pop(msg.cseq)
        del (self.original_msg.headers['CSeq'])
        self.original_msg.headers['Proxy-Authorization'] = str(Auth.from_authenticate_header(
            authenticate=msg.headers['Proxy-Authenticate'],
            method=msg.method,
            uri=str(self.to_details),
            username=self.to_details['uri']['user'],
            password=self.dialog.password))
        self.dialog.send_message(msg.method,
                                 headers=self.original_msg.headers,
                                 payload=self.original_msg.payload,
                                 future=self.futrue)

    def __repr__(self):
        return '<{0} cseq={1}, method={2}, dialog={3}>'.format(
            self.__class__.__name__, self.original_msg.cseq, self.original_msg.method, self.dialog
        )


class FutureTransaction(BaseTransaction):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._future = self.loop.create_future()

    async def start(self):
        self.retransmission = asyncio.ensure_future(self._timer())
        return await self._future

    def _incoming(self, msg):
        super()._incoming(msg)
        if msg.method == 'ACK':
            self._result(msg)
        elif msg.status_code == 401 and msg.auth:
            self._handle_authenticate(msg)
            return
        elif msg.status_code == 407:  # Proxy authentication
            self._handle_proxy_authenticate(msg)
            return
        elif self.original_msg.method.upper() == 'INVITE' and msg.status_code == 200:
            self.dialog.ack(msg)
            self._result(msg)
        elif 100 <= msg.status_code < 200:
            pass
        else:
            self._result(msg)

    def _error(self, error):
        if self.authentification:
            self.authentification.cancel()
            self.authentification = None
        self._future.set_exception(error)
        self.dialog.end_transaction(self)

    def _result(self, msg):
        if self.authentification:
            self.authentification.cancel()
            self.authentification = None
        self._future.set_result(msg)
        self.dialog.end_transaction(self)

    def close(self):
        if self._running:
            super().close()
            if not self._future.done():
                self._future.cancel()


class UnreliableTransaction(FutureTransaction):
    def close(self):
        if self._running and not self._future.done():
            self.dialog.cancel(cseq=self.original_msg.cseq)
        super().close()
