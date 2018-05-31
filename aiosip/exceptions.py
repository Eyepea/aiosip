
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
    def __init__(self):
        self.payload = None


class SIPNotFound(SIPError):
    status_code = 404


class SIPMethodNotAllowed(SIPError):
    status_code = 405


class SIPTransactionDoesNotExist(SIPError):
    status_code = 481


class SIPServerError(SIPError):
    status_code = 500

    def __init__(self, payload):
        self.payload = payload


class SIPNotImplemented(SIPError):
    status_code = 501
