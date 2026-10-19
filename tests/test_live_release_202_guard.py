"""Verify the live campaign fence without any network or real credentials."""
import json
import httpx
import pytest
from scripts.live_release_202 import Ledger,TEXT
from transcomic.providers import KIRA_CHAT_URL


def request(text=TEXT[0],url=KIRA_CHAT_URL):
    payload={'model':'configured','messages':[{},dict(content=json.dumps({'lines':[{'id':'stable-synthetic-id','text':text}]}))]}
    return httpx.Request('POST',url,json=payload)


def test_campaign_cannot_replay_or_exceed_two_five_attempt_cycles(tmp_path):
    path=tmp_path/'ledger.json';ledger=Ledger(path);ledger.data['model']='configured'
    for _ in range(5):ledger.reserve(request())
    with pytest.raises(RuntimeError):ledger.reserve(request())
    ledger.phase='manual_retry'
    for _ in range(5):ledger.reserve(request())
    with pytest.raises(RuntimeError):ledger.reserve(request())
    assert len(json.loads(path.read_text(encoding='utf-8'))['requests'])==10
    with pytest.raises(FileExistsError):Ledger(path)


def test_only_exact_authorized_synthetic_lines_and_endpoint(tmp_path):
    ledger=Ledger(tmp_path/'ledger.json');ledger.data['model']='configured'
    with pytest.raises(AssertionError):ledger.reserve(request('Private source not authorized'))
    with pytest.raises(AssertionError):ledger.reserve(request(url='https://example.invalid/chat'))
    assert ledger.data['requests']==[]
    ledger.data['stop_reason']='abnormal_token_usage'
    with pytest.raises(RuntimeError):ledger.reserve(request())
