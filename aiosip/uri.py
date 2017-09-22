import re

from collections import MutableMapping

from .param import Param


# Regex pattern from p2p-sip project
URI_PATTERN = re.compile('^(?P<scheme>[a-zA-Z][a-zA-Z0-9\+\-\.]*):'  # scheme
                         + '(?:(?:(?P<user>[a-zA-Z0-9\-\_\.!\~\*\'\(\)&=\+\$,;\?\/\%]+)'  # user
                         + '(?::(?P<password>[^:@;\?]+))?)@)?' # password
                         + '(?:(?:(?P<host>[^;\?:]*)(?::(?P<port>[\d]+))?))'  # host, port
                         + '(?:;(?P<params>[^\?]*))?' # parameters
                         + '(?:\?(?P<headers>.*))?$') # headers


class Uri(MutableMapping):
    def __init__(self, uri):
        self._uri = URI_PATTERN.match(uri).groupdict()
        if 'host' not in self._uri:
            raise ValueError('host is a mandatory field')
        elif self._uri['host'] == 'localhost':
            self._uri['host'] = '127.0.0.1'

        if self._uri['port']:
            self._uri['port'] = int(self._uri['port'])
        if self._uri['params']:
            self._uri['params'] = Param(self._uri['params'])

    def short_uri(self):
        r = ''
        if self._uri['scheme']:
            r += '%s:' % self._uri['scheme']
        if self._uri['user']:
            r += self._uri['user']
            if self._uri['password']:
                r += ':%s' % self._uri['password']
            r += '@'
        if self._uri['host']:
            r += self._uri['host']
        else:
            raise ValueError('host is a mandatory field')
        if self._uri['port']:
            r += ':%s' % self._uri['port']
        return r

    def optional_params(self):
        r = ''
        if self._uri['params']:
            r += ';%s' % self._uri['params']
        if self._uri['headers']:
            r += '?%s' % self._uri['headers']
        return r

    def contact_repr(self):
        r = '<%s>' % self.short_uri()
        return r

    def __str__(self):
        r = self.short_uri()
        r += self.optional_params()
        return r

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        return self._uri[key]

    def __setitem__(self, key, value):
        self._uri[key] = value

    def __delitem__(self, key):
        del self._uri[key]

    def __len__(self):
        return len(self._uri)

    def __iter__(self):
        return iter(self._uri)
