
class AiosipException(Exception): pass

class RegisterFailed(AiosipException): pass

class RegisterOngoing(AiosipException): pass
