import logging
import asyncio
import re
import uuid

from pyquery import PyQuery
from multidict import CIMultiDict

from . import utils
from .contact import Contact
from .auth import Auth

FIRST_LINE_PATTERN = {
    'request': {
        'regex': re.compile(r'(?P<method>[A-Za-z]+) (?P<to_uri>.+) SIP/2.0'),
        'str': '%(method)s %(to_uri)s SIP/2.0'},
    'response': {
        'regex': re.compile(r'SIP/2.0 (?P<status_code>[0-9]{3}) (?P<status_message>.+)'),
        'str': 'SIP/2.0 %(status_code)s %(status_message)s'},
}


LOG = logging.getLogger(__name__)


class Message:
    def __init__(self,
                 content_type=None,
                 headers=None,
                 payload=None,
                 from_details=None,
                 to_details=None,
                 contact_details=None,
                 ):

        self.from_details = from_details
        self.to_details = to_details
        self.contact_details = contact_details
        self.content_type = content_type

        self._payload = payload
        self._raw_payload = None

        if headers:
            self.headers = headers
        else:
            self.headers = CIMultiDict()

        if 'From' in self.headers:
            self.from_details = Contact.from_header(self.headers['From'])
        elif not self.from_details:
            raise ValueError('From header or from_details is required')

        if 'To' in self.headers:
            self.to_details = Contact.from_header(self.headers['To'])
        elif not self.to_details:
            raise ValueError('To header or to_details is required')

        if 'Contact' in self.headers:
            self.contact_details = Contact.from_header(self.headers['Contact'])

        if 'Via' not in self.headers:
            self.headers['Via'] = 'SIP/2.0/%(protocol)s '+'%s:%s;branch=%s' % (self.contact_details['uri']['host'],
                                                                               self.contact_details['uri']['port'],
                                                                               utils.gen_branch(10))

    @property
    def payload(self):
        if self._payload:
            return self._payload
        elif self._raw_payload:
            self._payload = self._raw_payload.decode()
            return self._payload
        else:
            return None

    @payload.setter
    def payload(self, payload):
        self._payload = payload

    @property
    def cseq(self):
        if not hasattr(self, '_cseq'):
            self._cseq = int(self.headers['CSeq'].split(' ')[0])
        return self._cseq

    @property
    def method(self):
        if not hasattr(self, '_method'):
            self._method = self.headers['CSeq'].split(' ')[1]
        return self._method

    def __str__(self):
        self.headers['From'] = str(self.from_details)
        self.headers['To'] = str(self.to_details)
        self.headers['Contact'] = str(self.contact_details)

        if 'Content-Length' not in self.headers:
            payload_len = len(self.payload.encode()) if self.payload else 0
            self.headers['Content-Length'] = payload_len

        if 'Max-Forwards' not in self.headers:
            self.headers['Max-Forwards'] = '70'
        if 'Call-ID' not in self.headers:
            self.headers['Call-ID'] = uuid.uuid4()

        if self.content_type:
            self.headers['Content-Type'] = self.content_type

        msg = []
        for k, v in sorted(self.headers.items()):
            if isinstance(v, (list, tuple)):
                msg.extend(['%s: %s' % (k, i) for i in v])
            else:
                msg.append('%s: %s' % (k, v))
        if self.payload:
            msg.append('%s%s' % (utils.EOL, self.payload))
        else:
            msg.append(utils.EOL)
        return utils.EOL.join(msg)

    def parsed_xml(self):
        if 'Content-Type' not in self.headers:
            return None
        if not self.headers['Content-Type'].endswith('+xml'):
            return None
        return PyQuery(self.payload).remove_namespaces()

    @classmethod
    def from_raw_headers(cls, raw_headers):
        headers = CIMultiDict()
        decoded_headers = raw_headers.decode().split(utils.EOL)
        for line in decoded_headers[1:]:
            try:
                k, v = line.split(': ', 1)
            except ValueError:
                LOG.warning(decoded_headers)
                LOG.warning(line)
                raise
            if k in headers:
                o = headers.setdefault(k, [])
                if not isinstance(o, list):
                    o = [o]
                o.append(v)
                headers[k] = o
            else:
                headers[k] = v

        m = FIRST_LINE_PATTERN['response']['regex'].match(decoded_headers[0])
        if m:
            d = m.groupdict()
            return Response(status_code=int(d['status_code']),
                            status_message=d['status_message'],
                            headers=headers)
        else:
            m = FIRST_LINE_PATTERN['request']['regex'].match(decoded_headers[0])
            if m:
                d = m.groupdict()
                cseq, _ = headers['CSeq'].split()

                return Request(method=d['method'],
                               headers=headers,
                               cseq=int(cseq))
            else:
                LOG.debug(decoded_headers)
                raise ValueError('Not a SIP message')


class Request(Message):
    def __init__(self,
                 method,
                 cseq=1,
                 from_details=None,
                 to_details=None,
                 contact_details=None,
                 headers=None,
                 content_type=None,
                 payload=None,
                 future=None,
                 ):

        super().__init__(
            content_type=content_type,
            headers=headers,
            payload=payload,
            from_details=from_details,
            to_details=to_details,
            contact_details=contact_details
        )

        self._method = method
        self._cseq = cseq
        self.future = future or asyncio.Future()

        if 'Authorization' in headers:
            self.auth = Auth.from_authorization_header(headers['Authorization'], self._method)
        else:
            self.auth = None

        if 'CSeq' not in self.headers:
            self.headers['CSeq'] = '%s %s' % (cseq, self.method)

    def __str__(self):
        message = FIRST_LINE_PATTERN['request']['str'] % {'method': self.method,
                                                          'to_uri': str(self.to_details['uri'].short_uri())}
        return '%s%s%s' % (message, utils.EOL, super().__str__())


class Response(Message):
    def __init__(self,
                 status_code,
                 status_message,
                 headers=None,
                 from_details=None,
                 to_details=None,
                 contact_details=None,
                 content_type=None,
                 payload=None,
                 cseq=None,
                 method=None,
                 ):

        self.status_code = status_code
        self.status_message = status_message

        super().__init__(
            content_type=content_type,
            headers=headers,
            payload=payload,
            from_details=from_details,
            to_details=to_details,
            contact_details=contact_details
        )

        if 'CSeq' not in self.headers and method and cseq:
            self.headers['CSeq'] = '%s %s' % (cseq, method)

    @classmethod
    def from_request(cls, request, status_code, status_message, payload=None, headers=None, content_type=None):

        if not headers:
            headers = CIMultiDict()

        if 'Via' not in headers:
            headers['Via'] = request.headers['Via']

        return Response(
            status_code=status_code,
            status_message=status_message,
            cseq=request.cseq,
            method=request.method,
            headers=headers,
            from_details=request.from_details,
            to_details=request.to_details,
            contact_details=request.contact_details,
            payload=payload,
            content_type=content_type
        )

    def __str__(self):
        message = FIRST_LINE_PATTERN['response']['str'] % self.__dict__
        return '%s%s%s' % (message, utils.EOL, super().__str__())
