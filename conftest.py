"""Root pytest configuration: unique external cache/tmp for every process."""
import os
import sys
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
def offline_release_network_guard(monkeypatch,request):
    """Automatic releases never spend translation API credits through tests."""
    if os.environ.get('TRANSCOMIC_RELEASE_OFFLINE_TESTS')!='1':return
    import httpx
    sync=httpx.Client._send_single_request;asynchronous=httpx.AsyncClient._send_single_request
    capture=None
    if request.path.name in ('test_semantic_v3.py','test_semantic_v4.py'):
        capture=getattr(sys.modules.get('scripts.benchmark_semantic_v3'),'Capture',None)

    def verify(client,outgoing):
        # Validate the selected transport, including mounts and redirect hops.
        transport=client._transport_for_url(outgoing.url)
        if capture is not None and type(transport) is capture:
            transport=transport.inner
        if not isinstance(transport,httpx.MockTransport):raise AssertionError('Automatic release tests require MockTransport')

    def guarded(client,outgoing):
        verify(client,outgoing)
        return sync(client,outgoing)
    async def guarded_async(client,outgoing):
        verify(client,outgoing)
        return await asynchronous(client,outgoing)
    monkeypatch.setattr(httpx.Client,'_send_single_request',guarded)
    monkeypatch.setattr(httpx.AsyncClient,'_send_single_request',guarded_async)
