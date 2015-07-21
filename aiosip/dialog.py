import asyncio
from collections import defaultdict
from aiohttp import multidict
from aiosip.auth import Auth

from .contact import Contact
from .log import dialog_logger
from .message import Request, Response
from functools import partial

class Dialog:
    def __init__(self,
                 app,
                 from_uri,
                 to_uri,
                 call_id,
                 protocol,
                 *,
                 local_addr=None,
                 remote_addr=None,
                 password='',
                 logger=dialog_logger,
                 loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        self.app = app
        self.from_details = Contact(from_uri)
        self.to_details = Contact(to_uri)
        self.call_id = call_id
        self.protocol = protocol
        self.local_addr = local_addr
        self.remote_addr = remote_addr
        self.password = password
        self.logger = logger
        self.loop = loop
        self.cseqs = defaultdict(int)
        self._msgs = defaultdict(dict)
        self.callbacks = defaultdict(list)

    def register_callback(self, method, callback, *args, **kwargs):
        self.callbacks[method.upper()].append({ 'callable': callback,
                                        'args' : args,
                                        'kwargs': kwargs})

    def is_callback_registered(self, method, callback):
        return len(filter(lambda e: e['callable']==callback, self.callbacks[method]))

    def unregister_callback(self, method, callback):
        for x in filter(lambda e: e['callable']==callback, self.callbacks[method]):
            self.callbacks[method].remove(x)

    def receive_message(self, msg):
        if isinstance(msg, Response):
            # import ipdb; ipdb.set_trace()
            if msg.cseq in self._msgs[msg.method]:
                if msg.status_code == 401:
                    original_msg = self._msgs[msg.method].pop(msg.cseq)
                    del(original_msg.headers['CSeq'])
                    original_msg.headers['Authorization'] = str(Auth.from_authenticate_header(
                        authenticate=msg.headers['WWW-Authenticate'],
                        method=msg.method,
                        uri=str(self.to_details),
                        username=self.to_details['uri']['user'],
                        password=self.password))
                    self.send_message(msg.method,
                                      headers=original_msg.headers,
                                      payload=original_msg.payload,
                                      future=original_msg.future)
                else:
                    self._msgs[msg.method].pop(msg.cseq).future.set_result(msg)  # Transaction end
            else:
                raise ValueError('This Response SIP message doesn\'t have Request: "%s"' % msg)
        else:
            hdrs = multidict.CIMultiDict()
            hdrs['Via'] = msg.headers['Via']
            hdrs['To'] = msg.headers['To']
            hdrs['From'] = msg.headers['From']
            hdrs['CSeq'] = msg.headers['CSeq']
            hdrs['Call-ID'] = msg.headers['Call-ID']
            resp = Response(status_code=200,
                            status_message='OK',  # aiosip is in da place !
                            headers=hdrs,
                            payload=None)
            self.app.send_message(type(self.protocol), self.local_addr, self.remote_addr, resp)

            for callback_info in self.callbacks[msg.method.upper()]:
                self.loop.call_soon(partial(callback_info['callable'], *((self, msg,) + callback_info['args']), **callback_info['kwargs']))

    def send_message(self, method, to_uri=None, headers=None, content_type=None, payload=None, future=None):
        if headers is None:
            headers = multidict.CIMultiDict()
        if 'Call-ID' not in headers:
            headers['Call-ID'] = self.call_id
        if to_uri:
            to_details = Contact(to_uri)
        else:
            to_details = self.to_details
        self.cseqs[method] += 1
        msg = Request(method=method,
                      from_details=self.from_details,
                      to_details=to_details,
                      cseq=self.cseqs[method],
                      headers=headers,
                      content_type=content_type,
                      payload=payload)
        if future:
            msg.future = future
        self._msgs[method][self.cseqs[method]] = msg
        self.app.send_message(type(self.protocol), self.local_addr, self.remote_addr, msg)

        return msg.future

    def register(self, headers=None):
        if not headers:
            headers = multidict.CIMultiDict()
        headers['Allow'] = 'INVITE, ACK, CANCEL, OPTIONS, BYE, REFER, SUBSCRIBE, NOTIFY, INFO, PUBLISH'
        headers['Expires'] = '360'
        headers['Allow-Events'] = 'talk,hold,conference,refer,check-sync'

        send_msg_future = self.send_message(method='REGISTER',
                                            headers=headers,
                                            payload='')
        return send_msg_future
