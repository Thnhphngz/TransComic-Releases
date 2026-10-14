"""Root pytest configuration: unique external cache/tmp for every process."""
import os
from pathlib import Path
import tempfile
import pytest
from scripts.test_runtime import session,outside
RUN=session()
os.environ['TRANSCOMIC_PYTEST_CACHE']=str(RUN/'cache')

@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    try:
        cache=Path(os.path.expandvars(config.getini('cache_dir')))
        outside(cache if cache.is_absolute() else config.rootpath/cache)
        selected=config.option.basetemp
        if selected:
            selected=outside(selected)
            if selected.exists():raise ValueError('Explicit --basetemp must be new, never existing user data')
        else:selected=RUN/'tmp'
        config.option.basetemp=str(selected)
        process_temp=RUN/'process-temp';process_temp.mkdir(exist_ok=True)
        os.environ['TMP']=os.environ['TEMP']=str(process_temp)
        tempfile.tempdir=None
        config._transcomic_test_runtime=RUN
    except (ValueError,OSError) as error:raise pytest.UsageError(str(error)) from error

def pytest_report_header(config):
    return 'TransComic external test runtime: '+str(RUN)

@pytest.fixture(autouse=True)
def offline_release_network_guard(monkeypatch):
    """Automatic releases never spend translation API credits through tests."""
    if os.environ.get('TRANSCOMIC_RELEASE_OFFLINE_TESTS')!='1':return
    import httpx
    sync=httpx.Client.send;asynchronous=httpx.AsyncClient.send
    def guarded(client,*args,**kwargs):
        if not isinstance(client._transport,httpx.MockTransport):raise AssertionError('Automatic release tests require MockTransport')
        return sync(client,*args,**kwargs)
    async def guarded_async(client,*args,**kwargs):
        if not isinstance(client._transport,httpx.MockTransport):raise AssertionError('Automatic release tests require MockTransport')
        return await asynchronous(client,*args,**kwargs)
    monkeypatch.setattr(httpx.Client,'send',guarded)
    monkeypatch.setattr(httpx.AsyncClient,'send',guarded_async)
