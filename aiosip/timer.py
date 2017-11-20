import asyncio
import functools
import logging


LOG = logging.getLogger(__name__)


T1 = 0.5  # RTT Estimate
T2 = 4.0  # The maximum retransmit interval for non-INVITE requests and INVITE responses
T4 = 5.0  # Maximum duration a message will remain in the network


class timer:
    def __init__(self, name, default):
        self.name = name
        self.default = default
        self.val = None

    def __call__(self):
        return self.val if self.val else self.default()

    def override(self, val):
        self.val = val

    def reset(self):
        self.val = None

    def __repr__(self):
        return 'timer(Timer %s)' % self.name


# INVITE request retransmit interval, for UDP only
timer_a = timer('A', lambda: T1)

# INVITE transaction timeout timer
timer_b = timer('B', lambda: T1 * 64)

# proxy INVITE transaction timeout
timer_c = timer('C', lambda: 180)

# Wait time for response retransmissions
timer_d = timer('D', lambda: 32)

# non-INVITE request retransmit interval, UDP only
timer_e = timer('E', lambda: T1)

# non-INVITE transaction timeout timer
timer_f = timer('F', lambda: T1 * 64)

# INVITE response retransmit interval
timer_g = timer('G', lambda: T1)

# Wait time for ACK receipt
timer_h = timer('H', lambda: T1 * 64)

# Wait time for ACK retransmits
timer_i = timer('I', lambda: T4)

# Wait time for non-INVITE request retransmits
timer_j = timer('J', lambda: T1 * 64)

# Wait time for response retransmits
timer_k = timer('K', lambda: T4)


def _retransmission_timer(callback, *, timeout, max_timeout):
    async def loop(timeout, max_timeout):
        while timeout <= max_timeout:
            callback()
            await asyncio.sleep(timeout)
            timeout *= 2

        raise asyncio.TimeoutError('SIP timer expired')

    LOG.debug("Starting sip timer...")
    future = asyncio.ensure_future(loop(timeout(), max_timeout()))
    future.add_done_callback(lambda f: LOG.debug("Stopping sip timer..."))
    return future


retransmit_invite = functools.partial(_retransmission_timer, timeout=timer_a, max_timeout=timer_b)
