import asyncio
import enum
import logging
from collections import defaultdict

from async_timeout import timeout as Timeout
from multidict import CIMultiDict

from . import utils
from .auth import Auth
from .message import Request, Response
from .transaction import ClientTransaction

LOG = logging.getLogger(__name__)


class Dialog:
    def __init__(self, app, message, response, transaction):
        self.app = app
        self.message = message
        self.responses = response
        self.transaction = transaction
