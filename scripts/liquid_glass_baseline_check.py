"""Reproduce the remaining lifecycle regression with pre-V3 UI snapshots."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM']='offscreen'
import transcomic.ui
transcomic.ui.__path__.insert(0,str(Path('artifacts/liquid-glass-v3/baseline-ui').resolve()))
import pytest
raise SystemExit(pytest.main([
    'tests/test_window_lifecycle.py::test_cancel_and_safe_exit_do_not_resend_inflight',
    '-q','--tb=short','--junitxml=artifacts/liquid-glass-v3/baseline-lifecycle.xml',
]))
