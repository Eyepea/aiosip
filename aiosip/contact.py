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
    def __init__(self, contact):
        for s in CONTACT_PATTERNS:
            m = s.match(contact)
            if m:
                super().__init__(m.groupdict())
                break
        else:
            raise ValueError('Not valid contact address')
        if self['params']:
            self['params'] = Param(self['params'])
        else:
            self['params'] = Param()
        if 'tag' not in self['params']:
            self['params']['tag'] = gen_str(16, string.digits + 'abcdef')
            contact_logger.debug('Contact: %s, params: %s', contact, self['params'])
        self['uri'] = Uri(self['uri'])

    def from_repr(self):
        return '%s;%s' % (str(self['uri']), self['params'])

    def __str__(self):
        r = ''
        if self['name']:
            r += '"%s" ' % self['name']
        return '%s%s;%s' % (r, self['uri'].contact_repr(), self['params'])
