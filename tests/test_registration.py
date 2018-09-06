from aiosip import auth


AUTH = {
    'auth_with_qop': 'Digest  realm="asterisk",'
                     'nonce="1535646722/5d9e709c8f2ccd74601946bfbd77b032",'
                     'algorithm=md5,'
                     'qop="auth",'
                     'nc="00000001",'
                     'response="7aafeb20b391dfb0af52c6d39bbef36e",'
                     'cnonce="0a4f113b"',
    'auth_without_qop': 'Digest  realm="asterisk",'
                        'nonce="1535646722/5d9e709c8f2ccd74601946bfbd77b032",'
                        'algorithm=md5,'
                        'response="05d233c1f0c0ef3d2fa203512363ce64"',
    'method': 'REGISTER',
    'uri': 'sip:5000@10.10.26.12',
    'username': '5000',
    'password': 'sangoma',
    'response_with_qop': '7aafeb20b391dfb0af52c6d39bbef36e',
    'response_without_qop': '05d233c1f0c0ef3d2fa203512363ce64'
}


def test_with_qop():
    authenticate = auth.Auth.from_authenticate_header(
        AUTH['auth_with_qop'],
        AUTH['method']
    )
    assert authenticate.validate_authorization(
        authenticate,
        password=AUTH['password'],
        username=AUTH['username'],
        uri=AUTH['uri']
    )


def test_without_qop():
    authenticate = auth.Auth.from_authenticate_header(
        AUTH['auth_without_qop'],
        AUTH['method']
    )
    assert authenticate.validate_authorization(
        authenticate,
        password=AUTH['password'],
        username=AUTH['username'],
        uri=AUTH['uri']
    )
