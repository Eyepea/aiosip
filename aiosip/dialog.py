import asyncio
import enum
import itertools
import logging
from collections import defaultdict

from async_timeout import timeout as Timeout
from multidict import CIMultiDict

from . import utils
from .auth import Auth
from .message import Request, Response
from .transaction import ClientTransaction

LOG = logging.getLogger(__name__)


class TransactionUser:
    pass


class Dialog:
    def __init__(self, app, message, response, transaction):
        self.app = app
        self.message = message
        self.response = response
        self.transaction = transaction
        self.cseq = itertools.count(20)

    async def send(self, method, *, headers=None, payload=None):
        return await self.transaction.peer.send_message(
            Request(
                method=method,
                from_details=self.response.to_details,
                to_details=self.response.from_details,
                contact_details=self.response.contact_details,
                headers=dict({
                    'Call-ID': self.response.headers['Call-ID'],
                    'Via': self.response.headers['Via']
                }, **(headers or {})),
                cseq=next(self.cseq),
                payload=payload))

    async def notify(self, payload):
        return await self.send('NOTIFY', payload=payload)

    async def __aiter__(self):
        yield await asyncio.Future()
