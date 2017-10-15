import asyncio
import contextlib
import gc
import sys

import pytest


try:
    import uvloop
except ImportError:  # pragma: no cover
    uvloop = None


try:
    import tokio
except ImportError:  # pragma: no cover
    tokio = None


LOOP_FACTORIES = []
LOOP_FACTORY_IDS = []


def pytest_addoption(parser):
    parser.addoption(
        '--fast', action='store_true', default=False,
        help='run tests faster by disabling extra checks')
    parser.addoption(
        '--loop', action='store', default='pyloop',
        help='run tests with specific loop: pyloop, uvloop, or all')
    parser.addoption(
        '--enable-loop-debug', action='store_true', default=False,
        help='enable event loop debug mode')


@contextlib.contextmanager
def loop_context(loop_factory=asyncio.new_event_loop, fast=False):
    """A contextmanager that creates an event_loop, for test purposes.

    Handles the creation and cleanup of a test loop.
    """
    loop = setup_test_loop(loop_factory)
    yield loop
    teardown_test_loop(loop, fast=fast)


def setup_test_loop(loop_factory=asyncio.new_event_loop):
    """Create and return an asyncio.BaseEventLoop instance.

    The caller should also call teardown_test_loop, once they are done
    with the loop.
    """
    loop = loop_factory()
    asyncio.set_event_loop(None)
    if sys.platform != "win32":
        policy = asyncio.get_event_loop_policy()
        watcher = asyncio.SafeChildWatcher()
        watcher.attach_loop(loop)
        policy.set_child_watcher(watcher)
    return loop


def teardown_test_loop(loop, fast=False):
    """Teardown and cleanup an event_loop created by setup_test_loop."""
    closed = loop.is_closed()
    if not closed:
        loop.call_soon(loop.stop)
        loop.run_forever()
        loop.close()

    if not fast:
        gc.collect()

    asyncio.set_event_loop(None)


def pytest_configure(config):
    loops = config.getoption('--loop')

    factories = {'pyloop': asyncio.new_event_loop}

    if uvloop is not None:  # pragma: no cover
        factories['uvloop'] = uvloop.new_event_loop

    if tokio is not None:  # pragma: no cover
        factories['tokio'] = tokio.new_event_loop

    LOOP_FACTORIES.clear()
    LOOP_FACTORY_IDS.clear()

    if loops == 'all':
        loops = 'pyloop,uvloop?,tokio?'

    for name in loops.split(','):
        required = not name.endswith('?')
        name = name.strip(' ?')
        if name in factories:
            LOOP_FACTORIES.append(factories[name])
            LOOP_FACTORY_IDS.append(name)
        elif required:
            raise ValueError(
                "Unknown loop '%s', available loops: %s" % (
                    name, list(factories.keys())))
    asyncio.set_event_loop(None)


def pytest_pycollect_makeitem(collector, name, obj):
    """Fix pytest collecting for coroutines."""
    if collector.funcnamefilter(name) and asyncio.iscoroutinefunction(obj):
        return list(collector._genfunctions(name, obj))


def pytest_pyfunc_call(pyfuncitem):
    """Run coroutines in an event loop instead of a normal function call."""
    if asyncio.iscoroutinefunction(pyfuncitem.function):
        testargs = {arg: pyfuncitem.funcargs[arg]
                    for arg in pyfuncitem._fixtureinfo.argnames}

        _loop = pyfuncitem.funcargs.get('loop', None)
        task = _loop.create_task(pyfuncitem.obj(**testargs))
        _loop.run_until_complete(task)

        return True


@pytest.fixture(params=LOOP_FACTORIES, ids=LOOP_FACTORY_IDS)
def loop(request):
    """Return an instance of the event loop."""
    fast = request.config.getoption('--fast')
    debug = request.config.getoption('--enable-loop-debug')

    with loop_context(request.param, fast=fast) as _loop:
        if debug:
            _loop.set_debug(True)  # pragma: no cover
        yield _loop
