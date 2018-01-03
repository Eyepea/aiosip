import asyncio


def session(function):
    tasks = {}

    async def closure(dialog, message):
        call_id = message.headers["Call-ID"]
        expires = int(message.headers["Expires"])

        await dialog.reply(message, status_code=200)

        if expires > 0:
            future = asyncio.ensure_future(function(dialog, message))
            tasks[call_id] = future
            await future
        else:
            future = tasks.get(call_id)
            if future and not future.done():
                future.cancel()

    return closure
