import logging

LOG = logging.getLogger(__name__)


class BaseDialplan:
    async def resolve(self, method, username, protocol, local_addr, remote_addr):
        LOG.debug('Resolving dialplan for %s %s connecting on %s from %s via %s',
                  method, username, local_addr, remote_addr, protocol)
