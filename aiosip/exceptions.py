
class AiosipException(Exception):
    pass


class AuthentificationFailed(PermissionError):
    pass


class RegisterFailed(AiosipException):
    pass


class RegisterOngoing(AiosipException):
    pass


class InviteFailed(AiosipException):
    pass


class InviteOngoing(AiosipException):
    pass


class SIPError(Exception):
    pass


class SIPNotFound(SIPError):
    status_code = 404


class SIPMethodNotAllowed(SIPError):
    status_code = 405


class SIPTransactionDoesNotExist(SIPError):
    status_code = 481
