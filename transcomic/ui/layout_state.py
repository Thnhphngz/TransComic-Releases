"""SQLite-backed layout preferences; restore after Qt has laid out widgets."""
import json
from PySide6.QtCore import QTimer


def capture(window):
    if getattr(window, '_restoring_layout', False) or not hasattr(window, 'document_splitter'): return
    sizes=window.document_splitter.sizes()
    if not window.document_panel.isHidden() and sizes[0]>0:
        window._document_width=sizes[0]
        window._splitter_sizes=sizes
    window.store.set_setting('layout_v2', json.dumps({
        'sidebar_compact':window.sidebar.width()<100,
        'sidebar_width':window.sidebar.width(),
        'documents_hidden':window.document_panel.isHidden(),
        'document_width':getattr(window,'_document_width',260),
        'splitter_sizes':getattr(window,'_splitter_sizes',sizes),
    }))


def install(window):
    window._restoring_layout=True
    try: state=json.loads(window.store.setting('layout_v2','{}'))
    except (ValueError,TypeError): state={}
    window._saved_layout=state if isinstance(state,dict) else {}
    window.layout_save_timer=QTimer(window); window.layout_save_timer.setSingleShot(True); window.layout_save_timer.setInterval(250)
    window.layout_save_timer.timeout.connect(lambda:capture(window))
    window.document_splitter.splitterMoved.connect(lambda *_:schedule(window))
    QTimer.singleShot(0,lambda:restore(window))


def schedule(window):
    if not getattr(window,'_restoring_layout',True) and not window._closed:
        window.layout_save_timer.start()


def restore(window):
    if window._closed:return
    state=window._saved_layout
    compact=bool(state.get('sidebar_compact',False)) or window.width()<1100
    if (window.sidebar.width()<100)!=compact:window.toggle_sidebar()
    saved_width=state.get('sidebar_width',200)
    if not compact and isinstance(saved_width,(int,float)):
        window.sidebar.setFixedWidth(min(240,max(160,int(saved_width))))
    total=max(1,window.document_splitter.width())
    width=state.get('document_width',260)
    if not isinstance(width,(int,float)):width=260
    width=min(max(window.document_panel.minimumWidth(),int(width)),max(window.document_panel.minimumWidth(),total-480))
    window._document_width=width
    window.document_splitter.setSizes([width,max(1,total-width)])
    hidden=bool(state.get('documents_hidden',False))
    window.document_panel.setVisible(not hidden);window.document_expand.setVisible(hidden)
    window._restoring_layout=False
    window.adapt_v2_toolbar()
