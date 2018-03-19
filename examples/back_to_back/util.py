class Registration:
    def __init__(self, peer, **kwargs):
        self._peer = peer
        self._kwargs = kwargs
        self._dialog = None

    async def __aenter__(self):
        self._dialog = await self._peer.register(**self._kwargs)

    async def __aexit__(self, *exc_info):
        await self._dialog.close()
