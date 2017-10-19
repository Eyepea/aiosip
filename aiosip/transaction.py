import asyncio
import logging

from multidict import CIMultiDict
from aiosip.auth import Auth

from .exceptions import RegisterFailed, InviteFailed


LOG = logging.getLogger(__name__)


@asyncio.coroutine
def sip_timer(sender, msg, *, timeout=0.5):
    max_timeout = timeout * 64
    while timeout <= max_timeout:
        sender(msg)
        yield from asyncio.sleep(timeout)
        timeout *= 2

    raise asyncio.TimeoutError('SIP timer expired for %s, %s, %s', msg.cseq, msg.method, msg.headers['Call-ID'])


class UnreliableTransaction:
    def __init__(self, dialog, original_msg=None, attempts=3,
                 future=None, *, loop=None):
        self.dialog = dialog
        self.original_msg = original_msg
        self.loop = loop or asyncio.get_event_loop()
        self.future = future or asyncio.Future(loop=self.loop)
        self.retransmission = None
        self.attempts = attempts

    def feed_message(self, msg):
        if self.retransmission:
            self.retransmission.cancel()
            self.retransmission = None

        if msg.status_code == 401 and 'WWW-Authenticate' in msg.headers:
            if self.dialog.password is None:
                raise ValueError('Password required for authentication')

            if msg.method.upper() == 'REGISTER':
                self.attempts -= 1
                if self.attempts < 1:
                    self.future.set_exception(
                        RegisterFailed('Too many unauthorized attempts!')
                    )
                    return
                username = msg.to_details['uri']['user']
            elif msg.method.upper() == 'INVITE':
                self.attempts -= 1
                if self.attempts < 1:
                    self.future.set_exception(
                        InviteFailed('Too many unauthorized attempts!')
                    )
                    return
                username = msg.from_details['uri']['user']

                hdrs = CIMultiDict()
                hdrs['From'] = msg.headers['From']
                hdrs['To'] = msg.headers['To']
                hdrs['Call-ID'] = msg.headers['Call-ID']
                hdrs['CSeq'] = msg.headers['CSeq'].replace(self.original_msg.method, 'ACK')
                hdrs['Via'] = msg.headers['Via']
                self.dialog.send(method='ACK', headers=hdrs)
            else:
                username = msg.from_details['uri']['user']

            del(self.original_msg.headers['CSeq'])
            self.original_msg.headers['Authorization'] = str(Auth.from_authenticate_header(
                authenticate=msg.headers['WWW-Authenticate'],
                method=msg.method,
                uri=msg.to_details['uri'].short_uri(),
                username=username,
                password=self.dialog.password))
            self.dialog.send(self.original_msg.method,
                             to_details=msg.to_details,
                             headers=self.original_msg.headers,
                             payload=self.original_msg.payload,
                             future=self.future)

        # for proxy authentication
        elif msg.status_code == 407:
            self.original_msg = self.original_msg.pop(msg.cseq)
            del(self.original_msg.headers['CSeq'])
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
        elif self.original_msg.method.upper() == 'INVITE' and msg.status_code == 200:
            hdrs = CIMultiDict()
            hdrs['From'] = msg.headers['From']
            hdrs['To'] = msg.headers['To']
            hdrs['Call-ID'] = msg.headers['Call-ID']
            hdrs['CSeq'] = msg.headers['CSeq'].replace('INVITE', 'ACK')
            hdrs['Via'] = msg.headers['Via']
            self.dialog.send(method='ACK', headers=hdrs)
            self.future.set_result(msg)
        elif 100 <= msg.status_code < 200:
            pass
        elif self.future.done():
            LOG.debug('Receive retransmission for %s, %s, %s', msg.cseq, msg.method, msg.headers['Call-ID'])
        else:
            self.future.set_result(msg)

    def start(self):
        if self.original_msg.method in ('REGISTER', 'INVITE', 'SUBSCRIBE'):
            self.future.add_done_callback(self._done_callback)

        self.retransmission = asyncio.ensure_future(sip_timer(self.dialog.peer.send_message, self.original_msg))
        return self.future

    def cancel(self):
        if self.retransmission:
            self.retransmission.cancel()
            self.retransmission = None

        hdrs = CIMultiDict()
        hdrs['From'] = self.original_msg.headers['From']
        hdrs['To'] = self.original_msg.headers['To']
        hdrs['Call-ID'] = self.original_msg.headers['Call-ID']
        hdrs['CSeq'] = self.original_msg.headers['CSeq'].replace(self.original_msg.method, 'CANCEL')
        hdrs['Via'] = self.original_msg.headers['Via']
        self.dialog.send(method='CANCEL', headers=hdrs)

    def _done_callback(self, result):
        if result.cancelled():
            self.cancel()

    def __await__(self):
        return self.future
