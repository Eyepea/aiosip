import re
import logging

from collections.abc import MutableMapping

from .param import Param


VIA_PATTERNS = [
    re.compile('SIP/2.0/(?P<protocol>[a-zA-Z]+)'
               '[ \t]*'
               '(?P<sentby>[^;]+)'
               '(?:;(?P<params>.*))'),
]


LOG = logging.getLogger(__name__)


class Via(MutableMapping):
    def __init__(self, *args, **kwargs):
        self._via = dict(*args, **kwargs)

        params = self._via.get('params')
        if not params:
            self._via['params'] = Param()
        if not isinstance(params, Param):
            self._via['params'] = Param(self._via['params'])

        self._via['host'], self._via['port'] = self._via['sentby'].rsplit(':', 1)

    @classmethod
    def from_header(cls, via):
        for s in VIA_PATTERNS:
            m = s.match(via)
            if m:
                return cls(m.groupdict())
        else:
            raise ValueError('Not valid via address')

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        return self._via[key]

    def __setitem__(self, key, value):
        self._via[key] = value

    def __delitem__(self, key):
        del self._via[key]

    def __len__(self):
        return len(self._via)

    def __iter__(self):
        return iter(self._via)
