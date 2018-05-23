import asyncio
from contextlib import suppress
import enum
import logging
import sys

import async_timeout

from aiosip.auth import Auth
from .exceptions import AuthentificationFailed

LOG = logging.getLogger(__name__)

PY_37 = sys.version_info >= (3, 7)

T1 = 0.5
T2 = 4
TIMER_A = T1
TIMER_B = T1 * 64
TIMER_D = 32  # not based on T1
TIMER_E = T1
TIMER_F = T1 * 64


def current_task(loop: asyncio.AbstractEventLoop) -> asyncio.Task:
    if PY_37:
        return asyncio.current_task(loop=loop)  # type: ignore
    else:
        return asyncio.Task.current_task(loop=loop)


class State(enum.Enum):
    Calling = 'calling'
    Proceeding = 'Proceeding'
    Completed = 'Completed'
    Terminated = 'Terminated'


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
    def __init__(self, *args):
        super().__init__(*args)
        self.queue = asyncio.Queue()

    async def start(self):
        self.transport.send(self.request, self.remote)
        self.state = State.Calling

        async def start_transaction():
            timeout = TIMER_A
            with async_timeout.timeout(TIMER_B):
                while self.state == State.Calling:
                    await self.transport.send(self.request, self.remote)
                    await asyncio.sleep(timeout)
                    timeout *= 2

        self.task = asyncio.ensure_future(start_transaction())

    async def received_response(self, response):
        if (100 <= response.status_code < 200
                and self.state in (State.Calling, State.Proceeding)):
            self.state = State.Proceeding
            await self.queue.put(response)

        elif (response.status_code == 200
              and self.state in (State.Calling, State.Proceeding)):
            self.state = State.Terminated
            self.ack()
            await self.queue.put(response)

        elif self.state in (State.Calling, State.Proceeding):
            self.state = State.Completed
            self.ack()

            async def _timer_d():
                await asyncio.wait(TIMER_D)
                self.state = State.Terminated

            asyncio.ensure_future(_timer_d())

    def ack(self):
        pass

    async def __aiter__(self):
        return self

    async def __anext__(self):
        await self.queue.wait()


class InviteServerTransaction(Transaction):
    async def start(self):
        self.state = State.Proceeding
        self.send_response(100, "Trying")
        # ... notify the user application

    def receive_request(self, request):
        # TODO: store the full original request
        if request.method == self.request.method:
            if self.state in (State.Proceeding, State.Completed):
                # retransmit last response
                pass
        elif request.method == 'ACK':
            if self.state == State.Completed:
                # self.state = State.Confirmed
                # Start task with TIMER_I to then flip to State.Terminated
                pass
            elif self.state == State.Confirmed:
                # Ignore ACKs
                pass

    def send(self, response):
        if (100 <= response.status_code < 200
                and self.state == State.Proceeding):
            pass  # TODO: send

        elif (response.status_code == 200 and self.state in State.Proceeding):
            self.state = State.Terminated
            pass  # TODO: send

        else:
            self.state = State.Completed
            # Failure. TODO: log
            # Start TIMER_G, abandon retransmissions


class ClientTransaction(Transaction):
    def start(self):
        self.transport.send(self.request, self.remote)
        self.state = State.Trying

        async def start_transaction():
            timeout = TIMER_E
            with async_timeout.timeout(TIMER_F):
                while self.state == State.Calling:
                    await self.transport.send(self.request, self.remote)
                    await asyncio.sleep(timeout)
                    timeout = min(timeout * 2, T2)

        self.task = asyncio.ensure_future(start_transaction())

    def received_response(self, response):
        if (100 <= response.status_code < 200
                and self.state in (State.Trying, State.Proceeding)):
            self.state = State.Proceeding
             # ... report
        else:
            self.state = State.Completed
             # ... report


class ServerTransaction(Transaction):
    def start(self):
        self.state = State.Trying

    def received_request(self, request):
        # Likely catching retransmissions
        if self.method == self.request.method:
            if self.state in (State.Proceeding, State.Completed):
                # TODO: retransmit last response
                pass
            elif self.state == State.Trying:
                # ignore
                pass

    def send_response(self, response):
        if (100 <= response.status_code < 200
                and self.state in (State.Trying, State.Proceeding)):
            self.state = State.Proceeding
            # send ...
        else:
            self.state = State.Completed
            # send ...


async def start_client_transaction(stack, app, request, transport, remote):
    cls = InviteClientTransaction if request.method == 'INVITE' else ClientTransaction
    transaction = cls(stack, app, request, transport, remote)
    await transaction.start()
    return transaction
