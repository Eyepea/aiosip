from collections import MutableMapping


class Dialplan:
    def __init__(self):
        self._dialplan = {}

    def add_user(self, user, handler):
        if user in self._dialplan:
            raise RuntimeError('Handler already registered for extension')

        self._dialplan[user] = handler

    def resolve(self, message):
        user = message.from_details['uri']['user']
        return self._dialplan.get(user, Router())


class Router(MutableMapping):
    def __init__(self):
        self._routes = {}

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        return self._routes[key.lower()]

    def __setitem__(self, key, value):
        self._routes[key.lower()] = value

    def __delitem__(self, key):
        del self._routes[key.lower()]

    def __len__(self):
        return len(self._routes)

    def __iter__(self):
        return iter(self._routes)
