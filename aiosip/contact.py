import re
import string
import logging

from collections import MutableMapping

from .param import Param
from .uri import Uri
from .utils import gen_str


# Regex pattern from p2p-sip project
CONTACT_PATTERNS = [re.compile('^(?P<name>[a-zA-Z0-9\-\._\+~ \t]*)<(?P<uri>[^>]+)>(?:;(?P<params>[^\?]*))?'),
                    re.compile('^(?:"(?P<name>[^"]+)")[ \t]*<(?P<uri>[^>]+)>(?:;(?P<params>[^\?]*))?'),
                    re.compile('^[ \t]*(?P<name>)(?P<uri>[^;]+)(?:;(?P<params>[^\?]*))?')]


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

    def from_repr(self):
        r = str(self._contact['uri'])
        params = self._contact['params']
        if params:
            r += ';%s' % str(params)
        return r

    def __str__(self):
        r = ''
        if 'name' in self._contact and self._contact['name']:
            r += '"%s" ' % self._contact['name']
        r += self._contact['uri'].contact_repr()
        params = self._contact['params']
        if params:
            r += ';%s' % str(params)
        return r

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
