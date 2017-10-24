import random
import string
import ipaddress

EOL = '\r\n'
BYTES_EOL = b'\r\n'

# From https://en.wikipedia.org/wiki/List_of_SIP_response_codes
STATUS = {
    100: 'Trying',
    180: 'Ringing',
    181: 'Call is Being Forwarded',
    182: 'Queued',
    183: 'Session in Progress',
    199: 'Early Dialog Terminated',
    200: 'OK',
    202: 'Accepted',
    204: 'No Notification',
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Moved Temporarily',
    305: 'Use Proxy',
    380: 'Alternative Service',
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Conditional Request Failed',
    413: 'Request Entity Too Large',
    414: 'Request-URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Unsupported URI Scheme',
    417: 'Unknown Resource-Priority',
    420: 'Bad Extension',
    421: 'Extension Required',
    422: 'Session Interval Too Small',
    423: 'Interval Too Brief',
    424: 'Bad Location Information',
    428: 'Use Identity Header',
    429: 'Provide Referrer Identity',
    430: 'Flow Failed',
    433: 'Anonymity Disallowed',
    436: 'Bad Identity-Info',
    437: 'Unsupported Certificate',
    438: 'Invalid Identity Header',
    439: 'First Hop Lacks Outbound Support',
    440: 'Max-Breadth Exceeded',
    469: 'Bad Info Package',
    470: 'Consent Needed',
    480: 'Temporarily Unavailable',
    481: 'Call/Transaction Does Not Exist',
    482: 'Loop Detected',
    483: 'Too Many Hops',
    484: 'Address Incomplete',
    485: 'Ambiguous',
    486: 'Busy Here',
    487: 'Request Terminated',
    488: 'Not Acceptable Here',
    489: 'Bad Event',
    491: 'Request Pending',
    493: 'Undecipherable',
    494: 'Security Agreement Required',
    500: 'Server Internal Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Server Time-out',
    505: 'Version Not Supported',
    513: 'Message Too Large',
    580: 'Precondition Failure',
    600: 'Busy Everywhere',
    603: 'Decline',
    604: 'Does Not Exist Anywhere',
    606: 'Not Acceptable',
    607: 'Unwanted'
}


def gen_str(length=10, letters=string.ascii_letters+string.digits):
    return "".join([random.choice(letters) for n in range(length)])


def gen_branch(length=10, letters=string.ascii_letters+string.digits):
    return "".join(("z9hG4bK", gen_str(length=length, letters=letters)))


async def get_host_ip(host, dns):
    try:
        return ipaddress.ip_address(host).exploded
    except ValueError:
        dns = await dns.query(host, 'A')
        return dns[0].host


async def get_proxy_peer(dialog, msg):
    host = await get_host_ip(msg.from_details['uri']['host'], dialog.app.dns)
    port = msg.from_details['uri']['port']

    if (host, port) == dialog.peer.peer_addr or (host, port) == dialog.contact_details:
        for peer in dialog.app.peers:
            if msg.method == 'NOTIFY':
                if msg.to_details['uri']['user'] in peer.subscriber:
                    return peer
            elif msg.to_details['uri']['user'] in peer.registered:
                return peer
        else:
            raise ValueError('No proxy peer found for {}'.format(msg))
    else:
        to_host = await get_host_ip(msg.to_details['uri']['host'], dialog.app.dns)
        to_port = msg.to_details['uri']['port']
        peer = await dialog.app.connect(remote_addr=(to_host, to_port), protocol=dialog.peer.protocol)
    return peer
