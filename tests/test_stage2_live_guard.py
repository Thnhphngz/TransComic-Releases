import sys
import pytest
from scripts import live_gemini_one


def test_prepare_does_not_open_database_or_send_http(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['live_gemini_one'])
    monkeypatch.setattr(live_gemini_one, 'OUT', tmp_path/'unused')
    monkeypatch.setattr(live_gemini_one.sqlite3, 'connect', lambda *a, **k: pytest.fail('Preparation must not open the user database'))
    assert live_gemini_one.main() == 0
    assert not live_gemini_one.OUT.exists()
    assert 'No API request sent' in capsys.readouterr().out


def test_live_permission_requires_new_explicit_authorization(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['live_gemini_one', '--allow-translation', '--model', 'models/mock'])
    with pytest.raises(SystemExit) as exc: live_gemini_one.main()
    assert exc.value.code == 2


def test_metadata_and_translation_reservations_independent_never_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(live_gemini_one, 'OUT', tmp_path)
    live_gemini_one.reserve('models', {'max_gets': 1})
    live_gemini_one.reserve('translation', {'max_posts': 1})
    for kind in ('models', 'translation'):
        with pytest.raises(FileExistsError): live_gemini_one.reserve(kind, {'changed_authorization': 'does-not-reset'})
