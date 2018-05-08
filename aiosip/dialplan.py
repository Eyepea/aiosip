import logging
import functools

from .message import Request

LOG = logging.getLogger(__name__)


class BaseDialplan:
    async def resolve(self, method, message, protocol, local_addr, remote_addr):
        LOG.debug('Resolving dialplan for %s %s connecting on %s from %s via %s',
                  method, message, local_addr, remote_addr, protocol)


class AuthDialplan(BaseDialplan):

    def __init__(self, child_dialplan):
        self.child_dialplan = child_dialplan

    async def resolve(self, *args, **kwargs):
        handler = await self.child_dialplan.resolve(*args, **kwargs)
        if handler:
            return functools.partial(self.authenticate, handler=handler)

    async def authenticate(self, request, message, handler):
        request.middlewares.append(self.check_auth)
        dialog = await request.unauthorized(message)
        await handler(dialog)

    async def check_auth(self, message, dialog):
        if isinstance(message, Request):
            password = await self.get_password(message, dialog)
            if not password or not dialog.validate_auth(message, password):
                await dialog.unauthorized(message)
                return

        return message

    async def get_password(self, message, dialog):
        return False
