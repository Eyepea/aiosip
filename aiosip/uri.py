import re

from .param import Param


# Regex pattern from p2p-sip project
URI_PATTERN = re.compile('^(?P<scheme>[a-zA-Z][a-zA-Z0-9\+\-\.]*):'  # scheme
                         + '(?:(?:(?P<user>[a-zA-Z0-9\-\_\.!\~\*\'\(\)&=\+\$,;\?\/\%]+)'  # user
                         + '(?::(?P<password>[^:@;\?]+))?)@)?' # password
                         + '(?:(?:(?P<host>[^;\?:]*)(?::(?P<port>[\d]+))?))'  # host, port
                         + '(?:;(?P<params>[^\?]*))?' # parameters
                         + '(?:\?(?P<headers>.*))?$') # headers

class Uri(dict):
    def __init__(self, uri):
        super().__init__(URI_PATTERN.match(uri).groupdict())
        if 'host' not in self:
            raise ValueError('host is a mandatory field')
        if self['port']:
            self['port'] = int(self['port'])
        if self['params']:
            self['params'] = Param(self['params'])

    def short_uri(self):
        r = ''
        if self['scheme']:
            r += '%s:' % self['scheme']
        if self['user']:
            r += self['user']
            if self['password']:
                r += ':%s' % self['password']
            r += '@'
        if self['host']:
            r += self['host']
        else:
            raise ValueError('host is a mandatory field')
        if self['port']:
            r += ':%s' % self['port']
        return r

    def optional_params(self):
        r = ''
        if self['params']:
            r += ';%s' % self['params']
        if self['headers']:
            r += '?%s' % self['headers']
        return r

    def contact_repr(self):
        r = '<%s>' % self.short_uri()
        return r

    def __str__(self):
        r = self.short_uri()
        r += self.optional_params()
        return r
