import asyncio
from contextlib import suppress
import enum
import logging

import async_timeout

from aiosip.auth import Auth
from .exceptions import AuthentificationFailed

LOG = logging.getLogger(__name__)


T1 = 0.5
TIMER_A = T1
TIMER_B = T1 * 64


class State(enum.Enum):
    Terminating = 'terminating'


class Transaction:
    def __init__(self, dialog, original_msg=None, attempts=3, *, loop=None):
        self.branch = None
        self.id = None
        self.stack = None
        self.app = None
        self.request = None
        self.transport = None
        self.remote = None
        self.tag = None

        self._state = None

        self.server = ...
        self.timers = {}
        self.timer = Timer()

        # self.dialog = dialog
        # self.original_msg = original_msg
        # self.loop = loop or asyncio.get_event_loop()
        # self.attempts = attempts
        # self.retransmission = None
        # self.authentification = None
        # self._running = True
        # LOG.debug('Creating: %s', self)

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        if self._status == State.Terminating:
            self.close()

    @property
    def headers(self):
        return set(self.request.headers[header]
                   for header in ('To', 'From', 'CSeq', 'Call-ID'))

    def close(self):
        # self.
        if self.app:
            with suppress(KeyError):
                del self.app.transactions[self.id]


class InviteClientTransaction(Transaction):
    async def start(self):
        self.transport.send(self.request, self.remote)
        self.state = State.Calling

        def start_transaction():
            timeout = TIMER_A
            with async_timeout.timeout(TIMER_B):
                while self.state == State.Calling:
                    await self.transport.send(self.request, self.remote)
                    await asyncio.sleep(timeout)
                    timeout *= 2

        self.task = asyncio.ensure_future(start_transaction())

    async def received_response(self, response):
        if 100 <= response.status_code < 200:
            self.state = State.Proceeding

        elif response.status_code == 200:
            self.state = State.Terminated

        elif 300 <= response.status_code < 700:
            self.state = State.Completed



class ClientTransaction(Transaction):
    async def start(self):
        pass


async def start_client_transaction(stack, app, request, transport, remote):
    cls = InviteClientTransaction if request.method == 'INVITE' else ClientTransaction
    transaction = cls(stack, app, request, transport, remote)
    await transaction.start()
    return transaction
