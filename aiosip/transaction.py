import asyncio

from multidict import CIMultiDict
from aiosip.auth import Auth

from .exceptions import RegisterFailed, InviteFailed


class UnreliableTransaction:
    def __init__(self, dialog, original_msg=None, attempts=3,
                 future=None, *, loop=None):
        self.dialog = dialog
        self.original_msg = original_msg
        self.loop = loop or asyncio.get_event_loop()
        self.future = future or asyncio.Future(loop=self.loop)
        self.attempts = attempts

        if original_msg.method in ('REGISTER', 'INVITE', 'SUBSCRIBE'):
            future.add_done_callback(self._done_callback)

    def feed_message(self, msg):
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
                hdrs['CSeq'] = msg.headers['CSeq'].replace(self.orignial_msg.method, 'ACK')
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
        else:
            self.future.set_result(msg)

    def cancel(self):
        hdrs = CIMultiDict()
        hdrs['From'] = self.original_msg.headers['From']
        hdrs['To'] = self.original_msg.headers['To']
        hdrs['Call-ID'] = self.original_msg.headers['Call-ID']
        hdrs['CSeq'] = self.original_msg.headers['CSeq'].replace(self.orignial_msg.method, 'CANCEL')
        hdrs['Via'] = self.original_msg.headers['Via']
        self.send_message(method='CANCEL', headers=hdrs)

    def _done_callback(self, result):
        if result.cancelled():
            self.cancel()

    def __await__(self):
        return self.future
