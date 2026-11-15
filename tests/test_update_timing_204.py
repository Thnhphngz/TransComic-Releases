"""Timing cannot bypass update safety or leak a startup ticket/exception body."""
import json
import os
from pathlib import Path
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QWidget
from transcomic.update.timing import UpdateTrace,startup_trace
from transcomic.ui.startup_ack import StartupAcknowledgement


def rows(trace):return [json.loads(s) for s in trace.path.read_text(encoding='utf8').splitlines()]


def test_timing_order_duration_redaction_and_legacy_ticket(tmp_path):
    ticket='b'*64;trace=startup_trace(['--update-startup-token='+ticket],tmp_path)
    with trace.span('database_open'):pass
    with pytest.raises(RuntimeError):
        with trace.span('restart'):raise RuntimeError('private manuscript path / api_key=secret')
    data=rows(trace);raw=trace.path.read_text()
    assert [r['stage'] for r in data]==['app_entry','database_open_started','database_open_finished','restart_started','restart_failed']
    assert data[-1]['error_type']=='RuntimeError' and data[-1]['duration_ms']>=0
    assert all(v not in raw for v in (ticket,'secret','manuscript','startup-token'))
    assert [r['elapsed_ms'] for r in data]==sorted(r['elapsed_ms'] for r in data)
    assert startup_trace([],tmp_path).path is None
    assert startup_trace(['--update-startup-token=../escape'],tmp_path).path is None


def test_timing_io_failure_does_not_change_result(tmp_path):
    trace=UpdateTrace(tmp_path);trace.path=tmp_path  # directory cannot be opened as a log file
    with trace.span('installer'):result=17
    assert result==17
    with pytest.raises(ValueError):trace.event('../escape')


@pytest.mark.parametrize('closing',[False,True])
def test_ack_waits_for_paint_and_gui_turn(tmp_path,monkeypatch,closing):
    if os.environ.get('TRANSCOMIC_NATIVE_UI')!='1':monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    w=QWidget();calls=[];trace=UpdateTrace(tmp_path)
    ack=StartupAcknowledgement(w,lambda:calls.append('ack'),trace)
    app.processEvents();assert not calls
    w._exit_pending=closing;w.show();QTest.qWait(80);app.processEvents()
    assert calls==([] if closing else ['ack'])
    if not closing:
        events=[r['stage'] for r in rows(trace)]
        assert events.index('window_painted')<events.index('startup_ack_started')<events.index('startup_ack_finished')
        w.update();QTest.qWait(20);assert calls==['ack']
    w.close()


def test_failed_ack_never_records_success(tmp_path,monkeypatch):
    if os.environ.get('TRANSCOMIC_NATIVE_UI')!='1':monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([]);w=QWidget();trace=UpdateTrace(tmp_path)
    def fail():raise OSError('receipt disk failure')
    ack=StartupAcknowledgement(w,fail,trace);w.show();QTest.qWait(80);app.processEvents()
    assert 'startup_ack_failed' in [r['stage'] for r in rows(trace)]
    assert 'startup_ack_finished' not in [r['stage'] for r in rows(trace)]
    w.close()
