import asyncio
import enum
import logging
import sys
from contextlib import suppress

import async_timeout

from .auth import Auth
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


# TODO: split invite from other transactions
class State(enum.Enum):
    Trying = 'Trying'
    Calling = 'Calling'
    Proceeding = 'Proceeding'
    Completed = 'Completed'
    Terminated = 'Terminated'


def new_branch():
    import secrets
    return ''.join(('z9hG4bK', secrets.token_urlsafe(6)))


class Transaction:
    def __init__(self, message, peer, *, loop=None):
        self.message = message
        self.peer = peer
        self.loop = loop or asyncio.get_event_loop()

        # TODO: akward API
        # TODO: sometimes will need to be pulled from the message
        self.message._branch = self.branch = new_branch()

        self.app = None
        self.remote = None
        self.tag = None

        self._state = None
        self._wait_for_completed = self.loop.create_future()

    @property
    def key(self):
        return self.message, self.branch

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value):
        self._state = value
        if self._state == State.Completed:
            self._wait_for_completed.set_result(None)
        if self._state == State.Terminated:
            self.close()

    @property
    def headers(self):
        return set(self.message.headers[header]
                   for header in ('To', 'From', 'CSeq', 'Call-ID'))

    def close(self):
        if self.app:
            with suppress(KeyError):
                del self.app.transactions[self.id]

    def set_exception(self, exception):
        self._wait_for_completed.set_exception(exception)
        self.state = State.Terminated

    async def completed(self):
        await self._wait_for_completed


class InviteClientTransaction(Transaction):
    def __init__(self, *args):
        super().__init__(*args)
        self.queue = asyncio.Queue()

    async def start(self):
        self.state = State.Calling

        async def start_transaction():
            timeout = TIMER_A
            with async_timeout.timeout(TIMER_B):
                while self.state == State.Calling:
                    await self.peer.send_message(self.message)
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
        if request.method == self.message.method:
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
    async def start(self):
        self.state = State.Trying

        async def start_transaction():
            timeout = TIMER_E
            try:
                with async_timeout.timeout(TIMER_F):
                    while self.state == State.Trying:
                        self.peer.send_message(self.message)
                        await asyncio.sleep(timeout)
                        timeout = min(timeout * 2, T2)
            except asyncio.TimeoutError as err:
                self.set_exception(err)

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
    async def start(self):
        self.state = State.Trying

    def received_request(self, request):
        # Likely catching retransmissions
        if self.method == self.message.method:
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
        else:
            self.state = State.Completed

        self.peer.send_message(response)


async def start_client_transaction(app, message, peer):
    cls = InviteClientTransaction if message.method == 'INVITE' else ClientTransaction
    transaction = cls(message, peer)
    app._transactions[(transaction.branch, message.method)] = transaction
    await transaction.start()
    return transaction


async def start_server_transaction(message, peer):
    cls = InviteServerTransaction if message.method == 'INVITE' else ServerTransaction
    transaction = cls(message, peer)
    await transaction.start()
    return transaction
