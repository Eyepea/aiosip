import asyncio
import logging

from aiosip.auth import Auth
from .exceptions import AuthentificationFailed


LOG = logging.getLogger(__name__)


class BaseTransaction:
    def __init__(self, dialog, original_msg=None, attempts=3, *, loop=None):
        LOG.debug('New Transaction for %s', dialog)
        self.dialog = dialog
        self.original_msg = original_msg
        self.loop = loop or asyncio.get_event_loop()
        self.attempts = attempts
        self.retransmission = None

    async def start(self):
        raise NotImplementedError

    def _incoming(self, msg):
        if self.retransmission:
            self.retransmission.cancel()
            self.retransmission = None

        if msg.method == 'ACK':
            return True
        if msg.status_code == 401 and 'WWW-Authenticate' in msg.headers:
            self._handle_authenticate(msg)
            return False
        elif msg.status_code == 407:  # Proxy authentication
            self._handle_proxy_authenticate(msg)
            return False
        elif self.original_msg.method.upper() == 'INVITE' and msg.status_code == 200:
            self.dialog.ack(msg)
        return True

    def _error(self, error):
        raise NotImplementedError

    def _result(self, msg):
        raise NotImplementedError

    def close(self):
        LOG.debug('Closing %s', self)

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

        if msg.method.upper() == 'REGISTER':
            self.attempts -= 1
            if self.attempts < 1:
                self._error(AuthentificationFailed('Too many unauthorized attempts!'))
                return
            username = msg.to_details['uri']['user']
        elif msg.method.upper() == 'INVITE':
            self.attempts -= 1
            if self.attempts < 1:
                self._error(AuthentificationFailed('Too many unauthorized attempts!'))
                return
            username = msg.from_details['uri']['user']
        else:
            username = msg.from_details['uri']['user']

        self.original_msg.cseq += 1
        self.original_msg.headers['Authorization'] = str(Auth.from_authenticate_header(
            authenticate=msg.headers['WWW-Authenticate'],
            method=msg.method,
            uri=msg.to_details['uri'].short_uri(),
            username=username,
            password=self.dialog.password)
        )

        self.dialog.transactions[self.original_msg.method][self.original_msg.cseq] = self
        self.dialog.peer.send_message(self.original_msg)

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


class QueueTransaction(BaseTransaction):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._incomings = asyncio.Queue()

    async def start(self):
        self.retransmission = asyncio.ensure_future(self._timer())
        while True:
            response = await self._incomings.get()
            if isinstance(response, BaseException):
                raise response
            elif response is None:
                return
            elif 100 <= response.status_code < 200:
                yield response
            else:
                yield response
                return

    def _incoming(self, msg):
        if super()._incoming(msg):
            self._incomings.put_nowait(msg)

    def _error(self, error):
        self._incomings.put_nowait(error)

    def _result(self, msg):
        self._incomings.put_nowait(msg)

    def close(self):
        super().close()
        self._incomings.put_nowait(None)


class FutureTransaction(BaseTransaction):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._future = self.loop.create_future()

    async def start(self):
        self.retransmission = asyncio.ensure_future(self._timer())
        return await self._future

    def _incoming(self, msg):
        if super()._incoming(msg):
            if msg.method == 'ACK':
                self._result(msg)
            elif 100 <= msg.status_code < 200:
                pass
            elif self._future.done():
                LOG.debug('Received response retransmission for %s, %s, %s',
                          msg.cseq, msg.method, msg.headers['Call-ID'])
            else:
                self._result(msg)

    def _error(self, error):
        self._future.set_exception(error)

    def _result(self, msg):
        self._future.set_result(msg)

    def close(self):
        super().close()
        self._future.cancel()


class UnreliableTransaction(FutureTransaction):
    pass
    # def cancel(self):
    #     if self.retransmission:
    #         self.retransmission.cancel()
    #         self.retransmission = None
    #
    #     hdrs = CIMultiDict()
    #     hdrs['From'] = self.original_msg.headers['From']
    #     hdrs['To'] = self.original_msg.headers['To']
    #     hdrs['Call-ID'] = self.original_msg.headers['Call-ID']
    #     hdrs['CSeq'] = self.original_msg.headers['CSeq'].replace(self.original_msg.method, 'CANCEL')
    #     hdrs['Via'] = self.original_msg.headers['Via']
    #     # self.dialog.reply(method='CANCEL', headers=hdrs)


class ProxyTransaction(QueueTransaction):
    def __init__(self, proxy_peer, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.proxy_peer = proxy_peer
        self._transmission = 0

    async def start(self):
        self.dialog.peer.send_message(self.original_msg)
        self._transmission, received = 1, 0
        while self._transmission != received:
            response = await self._incomings.get()
            if isinstance(response, BaseException):
                raise response
            elif response is None:
                return
            elif 100 <= response.status_code < 200:
                yield response
            else:
                received += 1
                yield response

    def _incoming(self, msg):
        self._incomings.put_nowait(msg)

    def retransmit(self):
        self._transmission += 1
        self.dialog.peer.send_message(self.original_msg)
