import asyncio


class Dialplan:
    def __init__(self):
        self._dialplan = {}

    def add_user(self, user, handler):
        if user in self._dialplan:
            raise RuntimeError('Handler already registered for extension')

        self._dialplan[user] = handler

    def resolve(self, message):
        user = message.from_details['uri']['user']
        return self._dialplan.get(user)
