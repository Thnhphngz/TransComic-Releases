"""Script entry point for PyInstaller."""

from pathlib import Path
import sys


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    from transcomic.dev_runtime import launch
    result=launch(Path(__file__).resolve().parent,sys.argv[1:])
    if result is not None:raise SystemExit(result)
    from transcomic.update.timing import startup_trace
    import os
    sys._transcomic_startup_trace=startup_trace(sys.argv[1:],Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'TransComic'/'Updates')
    from transcomic.app import main
    raise SystemExit(main())
