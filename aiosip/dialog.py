import asyncio
from collections import defaultdict
from multidict import CIMultiDict
from aiosip.auth import Auth

from .contact import Contact
from .log import dialog_logger
from .message import Request, Response
from .call import Call
from .exceptions import RegisterFailed, RegisterOngoing, InviteFailed, InviteOngoing
from .transaction import Transaction

from functools import partial


class Dialog:
    def __init__(self, *, logger=dialog_logger):
        self.logger = logger

    def connection_made(self,
                        app,
                        from_uri,
                        to_uri,
                        call_id,
                        protocol,
                        *,
                        contact_uri=None,
                        local_addr=None,
                        remote_addr=None,
                        password='',
                        loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self.app = app
        self.from_details = Contact.from_header(from_uri)
        self.to_details = Contact.from_header(to_uri)
        self.contact_details = Contact.from_header(contact_uri or from_uri)
        self.call_id = call_id
        self.protocol = protocol
        self.local_addr = local_addr
        self.remote_addr = remote_addr
        self.password = password
        self.loop = loop
        self.cseq = 0
        self._msgs = defaultdict(dict)
        self._pending = defaultdict(dict)
        self.callbacks = defaultdict(list)

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
                self.send_reply(status_code=200,
                                status_message='OK',
                                to_details=msg.to_details,
                                from_details=msg.from_details,
                                headers=hdrs,
                                payload=None)

            for callback_info in self.callbacks[msg.method.upper()]:
                if asyncio.iscoroutinefunction(callback_info['callable']):
                    fut = callback_info['callable'](*((self, msg,) + callback_info['args']), **callback_info['kwargs'])
                    asyncio.ensure_future(fut)
                else:
                    self.loop.call_soon(partial(callback_info['callable'], *((self, msg,) + callback_info['args']), **callback_info['kwargs']))

    def send_message(self, method, to_details=None, from_details=None, contact_details=None, headers=None, content_type=None, payload=None, future=None):
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
                      payload=payload)

        if future:
            msg.future = future

        if method != 'ACK':
            transaction = Transaction(self, password=self.password,
                                      future=future, loop=self.loop)

            self._msgs[method][self.cseq] = msg
            self._pending[method][self.cseq] = transaction
            self.protocol.send_message(msg, self.remote_addr)
            return transaction.future

        self.protocol.send_message(msg, self.remote_addr)
        return None

    def send_reply(self, status_code, status_message, to_details=None,
                   from_details=None, contact_details=None, headers=None, content_type=None,
                   payload=None, future=None):
        if headers is None:
            headers = CIMultiDict()
        if 'Call-ID' not in headers:
            headers['Call-ID'] = self.call_id

        if to_details:
            to_details = Contact(to_details)
        else:
            to_details = self.to_details
        to_details.add_tag()

        msg = Response(status_code=status_code,
                       status_message=status_message,
                       headers=headers,
                       to_details=to_details,
                       from_details=from_details if from_details else self.from_details,
                       contact_details=contact_details if contact_details else self.contact_details,
                       content_type=content_type,
                       payload=payload)
        if future:
            msg.future = future
        self.protocol.send_message(msg, self.remote_addr)

    def close(self):
        self.app.stop_dialog(self)

    def register(self, headers=None, attempts=3, expires=360):
        if not headers:
            headers = CIMultiDict()

        if 'Allow' not in headers:
            headers['Allow'] = 'INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, SUBSCRIBE, NOTIFY, INFO, PUBLISH'

        if 'Expires' not in headers:
            headers['Expires'] = int(expires)

        if 'Allow-Events' not in headers:
            headers['Allow-Events'] = 'talk,hold,conference,refer,check-sync'

        send_msg_future = self.send_message(method='REGISTER',
                                            headers=headers,
                                            payload='')
        return send_msg_future

    @asyncio.coroutine
    def invite(self, headers=None, sdp=None, attempts=3):
        if not headers:
            headers = CIMultiDict()

        send_msg_future = self.send_message(method='INVITE',
                                            headers=headers,
                                            payload=sdp)
        return send_msg_future
