from collections import MutableMapping


class Param(MutableMapping):
    def __init__(self, param=''):
        if param:
            self._param = dict(item.split("=") for item in param.split(";") if '=' in item)
        else:
            self._param = {}

    def __str__(self):
        return ';'.join('{}={}'.format(key, val) for key, val in self.items())

    # MutableMapping API
    def __eq__(self, other):
        return self is other

    def __getitem__(self, key):
        return self._param[key]

    def __setitem__(self, key, value):
        self._param[key] = value

    def __delitem__(self, key):
        del self._param[key]

    def __len__(self):
        return len(self._param)

    def __iter__(self):
        return iter(self._param)
