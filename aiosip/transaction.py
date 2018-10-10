import asyncio
import logging

from .exceptions import AuthentificationFailed


LOG = logging.getLogger(__name__)


class Transaction:
    def __init__(self, dialog, original_msg=None, attempts=3, *, loop=None):
        self.dialog = dialog
        self.original_msg = original_msg
        self.loop = loop or asyncio.get_event_loop()
        self.attempts = attempts
        self.retransmission = None
        self.authentification = None
        self._running = True
        self._response = asyncio.Future()
        LOG.debug('Creating: %s', self)

    async def start(self):
        self.retransmission = asyncio.ensure_future(self._timer())
        return await self._response

    def incoming(self, msg):
        if self.retransmission:
            self.retransmission.cancel()
            self.retransmission = None

        if self.authentification and msg.status_code not in (401, 407):
            self.authentification.cancel()
            self.authentification = None

        if msg.status_code == 401 and msg.auth:
            self._handle_authenticate(msg)
            return False
        elif msg.status_code >= 200:
            self._response.set_result(msg)
            self.dialog.end_transaction(self)

        return True

    def _error(self, error):
        if self.authentification:
            self.authentification.cancel()
            self.authentification = None
        self.dialog.end_transaction(self)

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

    def __repr__(self):
        return '<{0} cseq={1}, method={2}, dialog={3}>'.format(
            self.__class__.__name__, self.original_msg.cseq, self.original_msg.method, self.dialog
        )
