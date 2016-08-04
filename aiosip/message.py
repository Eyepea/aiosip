import asyncio
import re
import sys
import uuid

from multidict import CIMultiDict

from . import utils
from .contact import Contact
import aiosip
from pyquery import PyQuery

FIRST_LINE_PATTERN = \
    {'request':
         {'regex': re.compile(r'(?P<method>[A-Za-z]+) (?P<to_uri>.+) SIP/2.0'),
          'str': '%(method)s %(to_uri)s SIP/2.0'},
     'response':
         {'regex': re.compile(r'SIP/2.0 (?P<status_code>[0-9]{3}) (?P<status_message>.+)'),
          'str': 'SIP/2.0 %(status_code)s %(status_message)s'},
    }

class Message:
    def __init__(self,
                 # from_uri,
                 # to_uri,
                 content_type=None,
                 headers=None,
                 payload=None):
        # self.from_uri = from_uri
        # self.to_uri = to_uri
        if headers:
            self.headers = headers
        else:
            self.headers = CIMultiDict()

        for direction in ('From', 'To'): # parse From and To headers
            direction_attribute = '%s_details' % direction.lower()
            if direction in self.headers:
                if not hasattr(self, direction_attribute):
                    setattr(self,
                            direction_attribute,
                            Contact.from_header(self.headers[direction]))
            elif hasattr(self, direction_attribute):
                if direction == 'To':
                    self.headers[direction] = getattr(self,
                                                      direction_attribute)['uri'].short_uri()
                else:
                    self.headers[direction] = str(getattr(self,
                                                          direction_attribute))
            else:
                raise(ValueError('You must have a "%s" header or details.' % direction))

            if content_type:
                self.headers['Content-Type'] = content_type
        self.payload = payload
        if self.payload:
            self.headers['Content-Length'] = len(self.payload.encode())
        else:
            self.headers['Content-Length'] = 0

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
                return Request(method=d['method'],
                               headers=headers,
                               payload=payload)
            else:
                    raise ValueError('Not a SIP message')


class Request(Message):
    def __init__(self,
                 method,
                 cseq=1,
                 from_details=None,
                 to_details=None,
                 headers=None,
                 content_type=None,
                 payload=None):
        if from_details:
            self.from_details = from_details
        if to_details:
            self.to_details = to_details
        super().__init__(content_type=content_type,
                         headers=headers,
                         payload=payload)
        self._method = method
        self._cseq = cseq
        self.future = asyncio.Future()

        # Build the message
        if 'Via' not in self.headers:
            self.headers['Via'] = 'SIP/2.0/%(protocol)s '+'%s:%s' % (self.from_details['uri']['host'],
                                                                     self.from_details['uri']['port'])
        if 'Max-Forwards' not in self.headers:
            self.headers['Max-Forwards'] = '70'
        if 'Contact' not in self.headers:
            self.headers['Contact'] = self.to_details['uri'].short_uri()
        if 'Call-ID' not in self.headers:
            self.headers['Call-ID'] = uuid.uuid4()
        if 'CSeq' not in self.headers:
            self.headers['CSeq'] = '%s %s' % (cseq, self.method)
        if 'User-Agent' not in self.headers:
            self.headers['User-Agent'] = 'Python/{0[0]}.{0[1]}.{0[2]} aiosip/{1}'.format(
                sys.version_info, aiosip.__version__)
        if 'Content-Length' not in self.headers:
            self.headers['Content-Length'] = len(payload)

    def __str__(self):
        message = FIRST_LINE_PATTERN['request']['str'] % {'method': self.method,
                                                          'to_uri': str(self.to_details['uri'].short_uri())}
        return '%s%s%s' % (message, utils.EOL, super().__str__())


class Response(Message):
    def __init__(self,
                 status_code,
                 status_message,
                 headers=None,
                 content_type=None,
                 payload=None):
        self.status_code = status_code
        self.status_message = status_message
        super().__init__(content_type=content_type,
                         headers=headers,
                         payload=payload)

    def __str__(self):
        message = FIRST_LINE_PATTERN['response']['str'] % self.__dict__
        return '%s%s%s' % (message, utils.EOL, super().__str__())
