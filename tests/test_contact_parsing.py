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


def test_header_with_name():
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


def test_add_tag():
    header = aiosip.Contact.from_header('<sip:pytest@127.0.0.1:7000>')
    assert dict(header['params']) == {}

    header.add_tag()
    assert 'tag' in header['params']
