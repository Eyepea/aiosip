import logging

from collections import MutableMapping


LOG = logging.getLogger(__name__)


class Dialplan:
    def __init__(self, default=None):
        self._users = {}
        self.default = default

    async def resolve(self, username, protocol, local_addr, remote_addr):
        LOG.debug('Resolving dialplan for %s connecting on %s from %s via %s',
                  username, local_addr, remote_addr, protocol)
        router = self._users.get(username)
        if not router:
            router = self._users.get('*', self.default)
        return router

    def add_user(self, username, router):
        self._users[username] = router


class Router(MutableMapping):
    def __init__(self, default=None):
        self._routes = {}
        if default:
            self._routes['*'] = default

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        try:
            return self._routes[key.lower()]
        except KeyError:
            return self._routes['*']

    def __setitem__(self, key, value):
        self._routes[key.lower()] = value

    def __delitem__(self, key):
        del self._routes[key.lower()]

    def __len__(self):
        return len(self._routes)

    def __iter__(self):
        return iter(self._routes)
