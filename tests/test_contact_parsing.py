import aiosip


def test_simple_header():
    header = aiosip.Contact.from_header('<sip:pytest@127.0.0.1:7000>')
    assert not header['name']
    assert dict(header['params']) == {}
    assert dict(header['uri']) == {'scheme': 'sip',
                                   'user': 'pytest',
                                   'password': None,
                                   'host': '127.0.0.1',
                                   'port': 7000,
                                   'params': None,
                                   'headers': None}
    assert str(header) == '<sip:pytest@127.0.0.1:7000>'


def test_header_with_name_and_params():
    # RFC 3261 - 8.1.1.3
    header = aiosip.Contact.from_header('Anonymous <sip:c8oqz84zk7z@privacy.org>;tag=hyh8')
    assert header['name'] == "Anonymous"
    assert dict(header['params']) == {'tag': 'hyh8'}
    assert dict(header['uri']) == {'scheme': 'sip',
                                   'user': 'c8oqz84zk7z',
                                   'password': None,
                                   'host': 'privacy.org',
                                   'port': None,
                                   'params': None,
                                   'headers': None}
    assert str(header) == '"Anonymous" <sip:c8oqz84zk7z@privacy.org>;tag=hyh8'


def test_header_with_quoted_name():
    header = aiosip.Contact.from_header('"Pytest" <sip:pytest@127.0.0.1:7000>')
    assert header['name'] == "Pytest"
    assert dict(header['params']) == {}
    assert dict(header['uri']) == {'scheme': 'sip',
                                   'user': 'pytest',
                                   'password': None,
                                   'host': '127.0.0.1',
                                   'port': 7000,
                                   'params': None,
                                   'headers': None}
    assert str(header) == '"Pytest" <sip:pytest@127.0.0.1:7000>'


def test_header_with_quoted_name_and_space_before_params():
    # RFC 3261 - 8.1.1.3
    header = aiosip.Contact.from_header('"Bob" <sips:bob@biloxi.com> ;tag=a48s')
    assert header['name'] == 'Bob'
    assert dict(header['params']) == {'tag': 'a48s'}
    assert dict(header['uri']) == {'scheme': 'sips',
                                   'user': 'bob',
                                   'password': None,
                                   'host': 'biloxi.com',
                                   'port': None,
                                   'params': None,
                                   'headers': None}
    assert str(header) == '"Bob" <sips:bob@biloxi.com>;tag=a48s'


def test_header_without_brackets():
    # RFC 3261 - 8.1.1.3
    header = aiosip.Contact.from_header('sip:+12125551212@phone2net.com;tag=887s')
    assert not header['name']
    assert dict(header['params']) == {'tag': '887s'}
    assert dict(header['uri']) == {'scheme': 'sip',
                                   'user': '+12125551212',
                                   'password': None,
                                   'host': 'phone2net.com',
                                   'port': None,
                                   'params': None,
                                   'headers': None}
    assert str(header) == '<sip:+12125551212@phone2net.com>;tag=887s'


def test_add_tag():
    header = aiosip.Contact.from_header('<sip:pytest@127.0.0.1:7000>')
    assert dict(header['params']) == {}

    header.add_tag()
    assert 'tag' in header['params']
