import logging

from collections import MutableMapping


LOG = logging.getLogger(__name__)


class BaseDialplan:
    async def resolve(self, message, username, protocol, local_addr, remote_addr):
        LOG.debug('Resolving dialplan for %s connecting on %s from %s via %s',
                  username, local_addr, remote_addr, protocol)
