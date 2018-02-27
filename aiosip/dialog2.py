import asyncio
from collections import defaultdict
import enum
import logging

from multidict import CIMultiDict

from .dialog import Dialog
from .message import Request, Response
from .transaction import UnreliableTransaction


class CallState(enum.Enum):
    Calling = enum.auto()
    Proceeding = enum.auto()
    Completed = enum.auto()
    Terminated = enum.auto()


LOG = logging.getLogger(__name__)


class DialogSetup:
    def __init__(self,
                 app,
                 from_details,
                 to_details,
                 call_id,
                 peer,
                 contact_details,
                 *,
                 password=None,
                 router=None,
                 cseq=0):

        self.app = app
        self.from_details = from_details
        self.to_details = to_details
        self.contact_details = contact_details
        self.call_id = call_id
        self.peer = peer
        self.password = password
        self.cseq = cseq

        self.msg = self._prepare_request('INVITE')
        self.transactions = defaultdict(dict)

        self._dialog = None
        self._queue = asyncio.Queue()
        self._state = CallState.Calling
        self._waiter = asyncio.Future()

    @property
    def state(self):
        return self._state

    async def receive_message(self, msg):
        async def set_result(msg):
            self._ack(msg)
            if not self._waiter.done():
                self._waiter.set_result(msg)
            await self._queue.put(msg)

        if self._state == CallState.Calling:
            if 100 <= msg.status_code < 200:
                self._state = CallState.Proceeding

            elif msg.status_code == 200:
                self._state = CallState.Terminated
                await set_result(msg)

            elif 300 <= msg.status_code < 700:
                self._state = CallState.Completed
                await set_result(msg)

            pass

        elif self._state == CallState.Proceeding:
            if 100 <= msg.status_code < 200:
                await self._queue.put(msg)

            elif msg.status_code == 200:
                self._state = CallState.Terminated
                await set_result(msg)

            elif 300 <= msg.status_code < 700:
                self._state = CallState.Completed
                await set_result(msg)

            pass

        elif self._state == CallState.Completed:
            # Any additional messages in this state MUST be acked but
            # are NOT to be passed up
            self._ack(msg)
            # TODO: flip to Terminated after timeout
            pass

        elif self._state == CallState.Terminated:
            if isinstance(msg, Response) or msg.method == 'ACK':
                return self._receive_response(msg)
            else:
                return await self._receive_request(msg)

    def _receive_response(self, msg):
        try:
            transaction = self.transactions[msg.method][msg.cseq]
            transaction._incoming(msg)
        except KeyError:
            LOG.debug('Response without Request. The Transaction may already be closed. \n%s', msg)

    async def wait_for_terminate(self):
        while not self._waiter.done():
            yield await self._queue.get()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.close()

    def _get_dialog(self):
        if not self._dialog:
            self._dialog = Dialog(
                app=self.app,
                from_details=self.from_details,
                to_details=self.to_details,
                contact_details=self.contact_details,
                call_id=self.call_id,
                peer=self.peer,
                password=self.password,
                cseq=self.cseq,
            )

        return self._dialog

    async def start(self):
        self.peer.send_message(self.msg)

    async def close(self):
        msg = self._prepare_request('BYE')
        transaction = UnreliableTransaction(self, original_msg=msg, loop=self.app.loop)
        self.transactions[msg.method][msg.cseq] = transaction
        return await transaction.start()

    async def wait(self):
        msg = await self._waiter
        if msg.status_code != 200:
            raise RuntimeError("INVITE failed with {}".format(msg.status_code))
        return self._get_dialog

    def __repr__(self):
        return '<{} {} call_id={}, peer={}>'.format(self.__class__.__name__,
                                                    self.state, self.call_id,
                                                    self.peer)

    def _ack(self, msg, headers=None, *args, **kwargs):
        headers = CIMultiDict(headers or {})

        headers['Via'] = msg.headers['Via']
        ack = self._prepare_request('ACK', cseq=msg.cseq, to_details=msg.to_details, headers=headers, *args, **kwargs)
        self.peer.send_message(ack)

    def _prepare_request(self, method, contact_details=None, headers=None, payload=None, cseq=None, to_details=None):
        self.from_details.add_tag()
        if not cseq:
            self.cseq += 1

        if contact_details:
            self.contact_details = contact_details

        headers = CIMultiDict(headers or {})

        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.app.defaults['user_agent']

        headers['Call-ID'] = self.call_id

        msg = Request(
            method=method,
            cseq=cseq or self.cseq,
            from_details=self.from_details,
            to_details=to_details or self.to_details,
            contact_details=self.contact_details,
            headers=headers,
            payload=payload,
        )
        return msg

    def end_transaction(self, transaction):
        to_delete = list()
        for method, values in self.transactions.items():
            for cseq, t in values.items():
                if transaction is t:
                    transaction.close()
                    to_delete.append((method, cseq))

        for item in to_delete:
            del self.transactions[item[0]][item[1]]
