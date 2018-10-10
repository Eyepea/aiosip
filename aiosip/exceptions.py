
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


class SubscriptionFailed(AiosipException):
    pass
