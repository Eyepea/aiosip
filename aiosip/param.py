class Param(dict):
    def __init__(self, param=''):
        if param:
            super().__init__(dict(item.split("=") for item in param.split(";")))

    def __str__(self):
        return ';'.join('{}={}'.format(key, val) for key, val in self.items())
