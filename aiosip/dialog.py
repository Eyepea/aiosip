import asyncio
import logging

from collections import defaultdict
from multidict import CIMultiDict
from aiosip.auth import Auth

from .contact import Contact
from .log import dialog_logger
from .message import Request, Response
from .call import Call
from .exceptions import RegisterFailed, RegisterOngoing, InviteFailed, InviteOngoing

from functools import partial


LOG = logging.getLogger(__name__)


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
                hdrs['CSeq'] = msg.headers['CSeq'].replace('INVITE', 'ACK')
                hdrs['Via'] = msg.headers['Via']
                self.dialog.send(method='ACK', headers=hdrs)
            else:
                username = msg.from_details['uri']['user']

            del(original_msg.headers['CSeq'])
            original_msg.headers['Authorization'] = str(Auth.from_authenticate_header(
                authenticate=authenticate,
                method=msg.method,
                uri=msg.to_details['uri'].short_uri(),
                username=username,
                password=self.dialog.password))
            self.dialog.send(original_msg.method,
                             to_details=msg.to_details,
                             headers=original_msg.headers,
                             payload=original_msg.payload,
                             future=self.future)

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
        else:
            self.future.set_result(msg)

    def __await__(self):
        return self.future


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
        self._msgs = defaultdict(dict)
        self._pending = defaultdict(dict)
        self.callbacks = defaultdict(list)
        self._tasks = list()

    def register_callback(self, method, callback, *args, **kwargs):
        self.callbacks[method.upper()].append({'callable': callback,
                                               'args' : args,
                                               'kwargs': kwargs})

    def is_callback_registered(self, method, callback):
        return len(list(filter(lambda e: e['callable']==callback, self.callbacks[method])))

    def unregister_callback(self, method, callback):
        for x in filter(lambda e: e['callable']==callback, self.callbacks[method]):
            self.callbacks[method].remove(x)

    def receive_message(self, msg):
        if isinstance(msg, Response):
            if msg.cseq in self._msgs[msg.method]:
                original_msg = self._msgs[msg.method].get(msg.cseq)
                transaction = self._pending[msg.method].get(msg.cseq)
                transaction.feed_message(msg, original_msg=original_msg)
            else:
                raise ValueError('This Response SIP message doesn\'t have Request: "%s"' % msg)
        else:
            if msg.method != 'ACK':
                hdrs = CIMultiDict()
                hdrs['Via'] = msg.headers['Via']
                hdrs['CSeq'] = msg.headers['CSeq']
                hdrs['Call-ID'] = msg.headers['Call-ID']

                response = Response.from_request(
                    request=msg,
                    status_code=200,
                    status_message='OK',
                    headers=hdrs
                )
                self.reply(response)

            for callback_info in self.callbacks[msg.method.upper()]:
                if asyncio.iscoroutinefunction(callback_info['callable']):
                    fut = callback_info['callable'](*((self, msg,) + callback_info['args']), **callback_info['kwargs'])
                    self._tasks.append(asyncio.ensure_future(fut))
                else:
                    self.app.loop.call_soon(partial(callback_info['callable'], *((self, msg,) + callback_info['args']), **callback_info['kwargs']))

    def send(self, method, to_details=None, from_details=None, contact_details=None, headers=None, content_type=None, payload=None, future=None):

        if headers is None:
            headers = CIMultiDict()
        if 'Call-ID' not in headers:
            headers['Call-ID'] = self.call_id

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
            transaction = Transaction(self, password=self.password,
                                      future=msg.future, loop=self.app.loop)

            self._msgs[method][self.cseq] = msg
            self._pending[method][self.cseq] = transaction
            self.connection.send_message(msg)
            return transaction.future

        self.connection.send_message(msg)
        return None

    def reply(self, response):
        response.to_details.add_tag()
        response.headers['Call-ID'] = self.call_id
        self.connection.send_message(response)

    def close(self):
        self.connection._stop_dialog(self.call_id)
        for transactions in self._pending.values():
            for transaction in transactions.values():
                # transaction.cancel()
                if not transaction.future.done():
                    transaction.future.set_exception(ConnectionAbortedError)
        for task in self._tasks:
            task.cancel()

    def _connection_lost(self):
        for transactions in self._pending.values():
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
