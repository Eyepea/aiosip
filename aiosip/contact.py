import re
import string

from .log import contact_logger
from .param import Param
from .uri import Uri
from .utils import gen_str


# Regex pattern from p2p-sip project
CONTACT_PATTERNS = [re.compile('^(?P<name>[a-zA-Z0-9\-\._\+~ \t]*)<(?P<uri>[^>]+)>(?:;(?P<params>[^\?]*))?'),
                    re.compile('^(?:"(?P<name>[^"]+)")[ \t]*<(?P<uri>[^>]+)>(?:;(?P<params>[^\?]*))?'),
                    re.compile('^[ \t]*(?P<name>)(?P<uri>[^;]+)(?:;(?P<params>[^\?]*))?')]


class Contact(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        params = self.get('params')
        if not params:
            self['params'] = Param()
        if not isinstance(params, Param):
            self['params'] = Param(self['params'])

        uri = self.get('uri')
        if not isinstance(uri, Uri):
            self['uri'] = Uri(self['uri'])

    def add_tag(self):
        if 'tag' not in self['params']:
            self['params']['tag'] = gen_str(16, string.digits + 'abcdef')

    @classmethod
    def from_header(cls, contact):
        for s in CONTACT_PATTERNS:
            m = s.match(contact)
            if m:
                return cls(m.groupdict())
        else:
            raise ValueError('Not valid contact address')

    def from_repr(self):
        r = str(self['uri'])
        params = self['params']
        if params:
            r += ';%s' % str(params)
        return r


    def __str__(self):
        r = ''
        if self['name']:
            r += '"%s" ' % self['name']
        r += self['uri'].contact_repr()
        params = self['params']
        if params:
            r += ';%s' % str(params)
        return r
