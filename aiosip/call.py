import asyncio
from multidict import CIMultiDict


class Call:
    def __init__(self, dialog, headers, sdp, future=None):
        self.dialog = dialog
        self.dialog.register_callback('BYE', self.handle_bye)
        self.gotbye = future if future else asyncio.Future()
        self.original_headers = headers
        self.sdp = sdp

    @classmethod
    @asyncio.coroutine
    def invite(cls, dialog, headers=None, sdp=None, attempts=3, future=None):
        ok = yield from dialog.invite(headers=headers, sdp=sdp, attempts=attempts)
        assert ok.status_code == 200

        # TODO: come up with a better way of tracking cseq
        ok_cseq = int(ok.headers['CSeq'].split()[0])
        dialog.cseqs['ACK'] = ok_cseq - 1
        dialog.cseqs['BYE'] = ok_cseq

        self = cls(dialog, ok.headers, ok.payload, future=future)
        self._ack(ok)
        return self

    def _ack(self, msg):
        hdrs = CIMultiDict()
        hdrs['Via'] = self.original_headers['Via']
        hdrs['From'] = msg.headers['From']
        hdrs['To'] = msg.headers['To']
        hdrs['CSeq'] = msg.headers['CSeq'].replace('OK', 'ACK')
        self.dialog.send_message(method='ACK', headers=hdrs)

    def handle_bye(self, dialog, request):
        print('Call disconnected by remote...')
        self.gotbye.set_result(True)

    @asyncio.coroutine
    def close(self):
        self.dialog.unregister_callback('BYE', self.handle_bye)
        if not self.gotbye.done():
            hdrs = CIMultiDict()
            hdrs['Via'] = self.original_headers['Via']
            hdrs['From'] = self.original_headers['From']
            hdrs['To'] = self.original_headers['To']
            new_ok = yield from self.dialog.send_message(method='BYE',
                                                         headers=hdrs)
            assert new_ok.status_code == 200
            self._ack(new_ok)
            self.gotbye.set_result(True)

    @property
    def active(self):
        return self.gotbye.done

    @asyncio.coroutine
    def __aenter__(self):
        return self

    def wait(self):
        return self.gotbye

    @asyncio.coroutine
    def __aexit__(self, *exc_info):
        yield from self.close()
