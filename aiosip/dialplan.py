import logging

from . import utils
from collections import MutableMapping


LOG = logging.getLogger(__name__)


class Dialplan:
    def __init__(self, default=None):
        self._default = default
        self._dialplan = {}

    def add_user(self, user, handler):
        if user in self._dialplan:
            raise RuntimeError('Handler already registered for extension')

        self._dialplan[user] = handler

    def resolve(self, message):
        user = message.from_details['uri']['user']
        try:
            return self._dialplan[user]
        except KeyError:
            if self._default:
                return self._default
            else:
                return Router()

    def get_user(self, user):
        return self._dialplan.get(user)


class Router(MutableMapping):
    def __init__(self, default=None):
        self._routes = {'*': default}

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


class ProxyRouter(Router):
    def __init__(self):
        super().__init__(default=self.proxy)

    async def proxy(self, dialog, msg):
        peer = await utils.get_proxy_peer(dialog, msg)
        proxy_response = await peer.proxy_request(dialog, msg)
        if proxy_response:
            dialog.peer.proxy_response(proxy_response)
