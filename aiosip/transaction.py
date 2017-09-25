import asyncio
from collections import defaultdict
from multidict import CIMultiDict
from aiosip.auth import Auth

from .contact import Contact
from .log import dialog_logger
from .message import Request, Response
from .call import Call
from .exceptions import RegisterFailed, RegisterOngoing, InviteFailed, InviteOngoing

from functools import partial


class Transaction:
    def __init__(self, dialog, password=None, attempts=3, future=None,
                 *, loop=None):
        self.dialog = dialog
        self.loop = loop or asyncio.get_event_loop()
        self.future = future or asyncio.Future(loop=self.loop)
        self.attempts = attempts

    def feed_message(self, msg, original_msg=None):
        authenticate = msg.headers.get('WWW-Authenticate')
        if msg.status_code == 401 and authenticate:
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
                hdrs['CSeq'] = msg.headers['CSeq'].replace('INVITE', 'ACK')
                hdrs['Via'] = msg.headers['Via']
                self.dialog.send_message(method='ACK', headers=hdrs)
            else:
                username = msg.from_details['uri']['user']

            del(original_msg.headers['CSeq'])
            original_msg.headers['Authorization'] = str(Auth.from_authenticate_header(
                authenticate=authenticate,
                method=msg.method,
                uri=msg.to_details['uri'].short_uri(),
                username=username,
                password=self.password))
            self.dialog.send_message(original_msg.method,
                                     to_details=original_msg.to_details,
                                     headers=original_msg.headers,
                                     payload=original_msg.payload,
                                     future=self.futrue)

        # for proxy authentication
        elif msg.status_code == 407:
            original_msg = self._msgs[msg.method].pop(msg.cseq)
            del(original_msg.headers['CSeq'])
            original_msg.headers['Proxy-Authorization'] = str(Auth.from_authenticate_header(
                authenticate=msg.headers['Proxy-Authenticate'],
                method=msg.method,
                uri=str(self.to_details),
                username=self.to_details['uri']['user'],
                password=self.password))
            self.dialog.send_message(msg.method,
                                     headers=original_msg.headers,
                                     payload=original_msg.payload,
                                     future=self.futrue)

        elif 100 <= msg.status_code < 200:
            pass
        elif not self.future.done():
            self.future.set_result(msg)

    def __await__(self):
        return self.future
