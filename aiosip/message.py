import logging
import asyncio
import re
import sys
import uuid

from multidict import CIMultiDict

from . import utils
from .contact import Contact
import aiosip
from pyquery import PyQuery

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
                 contact_details=None):

        self.from_details = from_details
        self.to_details = to_details
        self.contact_details = contact_details

        if headers:
            self.headers = headers
        else:
            self.headers = CIMultiDict()

        if 'From' in self.headers:
            self.from_details = Contact.from_header(self.headers['From'])
        elif self.from_details:
            self.headers['From'] = str(self.from_details)
        else:
            raise ValueError('From header or from_details is required')

        if 'To' in self.headers:
            self.to_details = Contact.from_header(self.headers['To'])
        elif self.to_details:
            self.headers['To'] = str(self.to_details)
        else:
            raise ValueError('To header or to_details is required')

        if 'Contact' in self.headers:
            self.contact_details = Contact.from_header(self.headers['Contact'])
        elif self.contact_details:
            self.headers['Contact'] = str(self.contact_details)

        if content_type:
            self.headers['Content-Type'] = content_type

        self.payload = payload

        # Build the message
        if 'Via' not in self.headers:
            self.headers['Via'] = 'SIP/2.0/%(protocol)s '+'%s:%s;branch=%s' % (self.contact_details['uri']['host'],
                                                                               self.contact_details['uri']['port'],
                                                                               utils.gen_branch(10))
        if 'Max-Forwards' not in self.headers:
            self.headers['Max-Forwards'] = '70'
        if 'Call-ID' not in self.headers:
            self.headers['Call-ID'] = uuid.uuid4()
        if 'User-Agent' not in self.headers:
            self.headers['User-Agent'] = 'Python/{0[0]}.{0[1]}.{0[2]} aiosip/{1}'.format(
                sys.version_info, aiosip.__version__)
        if 'Content-Length' not in self.headers:
            payload_len = len(self.payload.encode()) if self.payload else 0
            self.headers['Content-Length'] = payload_len

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
    def from_raw_message(cls, raw_message):
        lines = raw_message.split(utils.EOL)
        first_line = lines.pop(0)
        headers = CIMultiDict()
        payload = ''
        reading_headers = True
        for line in lines:
            if reading_headers:
                if ': ' in line:
                    k, v = line.split(': ', 1)
                    if k in headers:
                        o = headers.setdefault(k, [])
                        if not isinstance(o, list):
                            o = [o]
                        o.append(v)
                        headers[k] = o
                    else:
                        headers[k] = v
                else:  # Finish to parse headers
                    reading_headers = False
            else: # @todo: use content length to read payload
                payload += line  # reading payload
        if payload == '':
            payload = None

        m = FIRST_LINE_PATTERN['response']['regex'].match(first_line)
        if m:
            d = m.groupdict()
            return Response(status_code=int(d['status_code']),
                            status_message=d['status_message'],
                            headers=headers,
                            payload=payload)
        else:
            m = FIRST_LINE_PATTERN['request']['regex'].match(first_line)
            if m:
                d = m.groupdict()
                cseq, _ = headers['CSeq'].split()
                return Request(method=d['method'],
                               headers=headers,
                               payload=payload,
                               cseq=int(cseq))
            else:
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
                 future=None):

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
