import re
import string
import logging

from collections.abc import MutableMapping

from .param import Param
from .uri import Uri
from .utils import gen_str


CONTACT_PATTERNS = [
    # unquoted name
    re.compile(r'^(?P<name>[a-zA-Z0-9\-\.!%\*_\+`\'~]*)'
               r'[ \t]*'
               r'<(?P<uri>[^>]+)>'
               r'[ \t]*'
               r'(?:;(?P<params>[^\?]*))?'),
    # quoted name
    re.compile(r'^(?:"(?P<name>[^"]+)")'
               r'[ \t]*'
               r'<(?P<uri>[^>]+)>'
               r'[ \t]*'
               r'(?:;(?P<params>[^\?]*))?'),
    # no name
    re.compile(r'(?P<name>)'
               r'[ \t]*'
               r'(?P<uri>[^ ;]+)'
               r'[ \t]*'
               r'(?:;(?P<params>[^\?]*))?'),
]


LOG = logging.getLogger(__name__)


class Contact(MutableMapping):
    def __init__(self, *args, **kwargs):
        self._contact = dict(*args, **kwargs)

        params = self._contact.get('params')
        if not params:
            self._contact['params'] = Param()
        if not isinstance(params, Param):
            self._contact['params'] = Param(self._contact['params'])

        uri = self._contact.get('uri')
        if not isinstance(uri, Uri):
            self._contact['uri'] = Uri(self._contact['uri'])

    def add_tag(self):
        if 'tag' not in self._contact['params']:
            self._contact['params']['tag'] = gen_str(16, string.digits + 'abcdef')

    @classmethod
    def from_header(cls, contact):
        for s in CONTACT_PATTERNS:
            m = s.match(contact)
            if m:
                return cls(m.groupdict())
        else:
            raise ValueError('Not valid contact address')

    def __str__(self):
        r = ''
        if self._contact.get('name'):  # Check if name exist and is not empty
            r += '"%s" ' % self._contact['name']
        r += self._contact['uri'].contact_repr()
        params = self._contact['params']
        if params:
            r += ';%s' % str(params)
        return r

    @property
    def scheme(self):
        return self._contact['uri']['scheme']

    @property
    def transport(self):
        transport = self._contact['params'].get('transport')
        if not transport:
            return 'tcp' if self.scheme == 'sips' else 'udp'
        return transport

    @property
    def host(self):
        return self._contact['uri']['host']

    @property
    def port(self):
        port = self._contact['uri'].get('port')
        if not port:
            if self.scheme == 'sips':
                return 5061
            elif self.transport == 'udp':
                return 5060
            else:
                return 5080
        return port

    @property
    def details(self):
        return self.scheme, self.transport, self.host, self.port

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        return self._contact[key]

    def __setitem__(self, key, value):
        self._contact[key] = value

    def __delitem__(self, key):
        del self._contact[key]

    def __len__(self):
        return len(self._contact)

    def __iter__(self):
        return iter(self._contact)
