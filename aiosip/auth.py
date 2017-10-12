from hashlib import md5
from collections import MutableMapping


def md5digest(*args):
    return md5(':'.join(args).encode()).hexdigest()


class Auth(MutableMapping):
    def __init__(self, mode='Digest', **kwargs):
        self._auth = kwargs
        self.mode = mode

        if self.mode != 'Digest':
            raise ValueError('Authentication method not supported')

    def __str__(self):
        if self.mode == 'Digest':
            r = 'Digest '
            l = []
            # import ipdb; ipdb.set_trace()
            for k, v in self._auth.items():
                if k == 'algorithm':
                    l.append('%s=%s' % (k, v))
                else:
                    l.append('%s="%s"' % (k, v))
            r += ','.join(l)
        else:
            raise ValueError('Authentication method not supported')
        return r

    @classmethod
    def from_authenticate_header(cls, authenticate, method, uri, username, password):
        if authenticate.startswith('Digest'):
            params = {
                'username': username,
                'uri': uri
            }
            params.update(cls.__parse_digest(authenticate))
            auth = cls(mode='Digest', **params)
            ha1 = md5digest(username, auth['realm'], password)
            ha2 = md5digest(method, uri)
            auth['response'] = md5digest(ha1, auth['nonce'], ha2)
        else:
            raise ValueError('Authentication method not supported')
        return auth

    @classmethod
    def from_authorization_header(cls, authorization, method):
        if authorization.startswith('Digest'):
            params = {'method': method}
            params.update(cls.__parse_digest(authorization))

            if 'response' not in params:
                raise ValueError('No authentification response')

            auth = cls(mode='Digest', **params)
        else:
            raise ValueError('Authentication method not supported')
        return auth

    @classmethod
    def __parse_digest(cls, header):
        params = {}
        args = header[7:].split(', ')
        for arg in args:
            k, v = arg.split('=')
            if '="' in arg:
                v = v[1:-1]
            params[k] = v
        return params

    def validate(self, password, nonce=None, username=None, realm=None, uri=None):

        if not username:
            username = self._auth['username']
        if not realm:
            realm = self._auth['realm']
        if not uri:
            uri = self._auth['uri']
        if not nonce:
            if 'server_nonce' not in self._auth:
                return False
            else:
                nonce = self._auth['server_nonce']

        ha1 = md5digest(username, realm, password)
        ha2 = md5digest(self._auth['method'], uri)
        rep = md5digest(ha1, nonce, ha2)
        return self._auth['response'] == rep

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        return self._auth[key]

    def __setitem__(self, key, value):
        self._auth[key] = value

    def __delitem__(self, key):
        del self._auth[key]

    def __len__(self):
        return len(self._auth)

    def __iter__(self):
        return iter(self._auth)
