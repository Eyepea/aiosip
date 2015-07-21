from hashlib import md5


class Auth(dict):
    # def __init__(self):
    #     super().__init__()

    def __str__(self):
        if self.method == 'Digest':
            r = 'Digest '
            l = []
            # import ipdb; ipdb.set_trace()
            for k, v in self.items():
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
        auth = cls()
        if authenticate.startswith('Digest'):
            auth.method = 'Digest'
            params = authenticate[7:].split(', ')
            for param in params:
                k, v = param.split('=')
                if '="' in param:
                    v = v[1:-1]
                auth[k] = v
            auth['username'] = username
            auth['uri'] = uri
            ha1 = md5(('%(username)s:%(realm)s:%(password)s' %
                      {'username': username,
                       'realm': auth['realm'],
                       'password': password}).encode())
            ha2 = md5(('%(method)s:%(uri)s' %
                      {'method': method, 'uri': uri}).encode())
            auth['response'] = md5(('%(ha1)s:%(nonce)s:%(ha2)s' %
                                    {'ha1': ha1.hexdigest(),
                                     'nonce': auth['nonce'],
                                     'ha2': ha2.hexdigest()}).encode()).hexdigest()
        else:
            raise ValueError('Authentication method not supported')
        return auth
