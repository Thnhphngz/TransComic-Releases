"""Source launcher uses a verified project environment; frozen apps never re-exec."""
import os
from pathlib import Path
import subprocess
import sys


def project_python(root):
    root=Path(root)
    return root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def launch(root,argv):
    if getattr(sys,'frozen',False):return None
    python=project_python(root);marker=python.parents[1]/'.transcomic-ready'
    if not python.is_file() or not marker.is_file() or Path(sys.prefix).resolve()==python.parents[1].resolve():return None
    return subprocess.call([str(python),str(Path(root)/'run_transcomic.py'),*argv])
