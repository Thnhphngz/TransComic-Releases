"""One explicit export policy for single and workspace exports."""
from pathlib import Path
from PySide6.QtWidgets import QInputDialog, QFileDialog, QMessageBox
from ..bulk import plan_exports, workspace_status

MODES = [('Xuất trực tiếp cạnh file nguồn', 'direct'),
         ('Xuất vào TransComic/<Ngôn ngữ> cạnh nguồn', 'transcomic'),
         ('Chọn thư mục khác', 'custom')]


def choose_export_plan(owner, ids):
    store = owner.store
    previous = store.setting('export_mode', 'transcomic')
    index = next((i for i, (_, mode) in enumerate(MODES) if mode == previous), 1)
    choice, ok = QInputDialog.getItem(owner, 'Phương thức xuất', 'Chọn vị trí xuất:', [label for label, _ in MODES], index, False)
    if not ok: return None
    mode = dict(MODES)[choice]; root = None
    snapshot = store.export_snapshot(ids)
    from ..line_structure import validate_snapshot
    checked = [(doc, rows, validate_snapshot(doc, rows)) for doc, rows in snapshot]
    blocked = [doc for doc, rows, report in checked if report.structural]
    if blocked:
        QMessageBox.warning(owner, 'Không thể xuất: phát hiện lỗi cấu trúc dòng.',
            'Các tài liệu sau bị chặn, không ghi file:\n'+'\n'.join(Path(doc['path']).name+' · '+doc['target_lang'] for doc in blocked)+
            '\nMở Kiểm tra số dòng để xem chi tiết. Các tài liệu hợp lệ khác vẫn có thể xuất.')
        if owner.doc_id in {doc['id'] for doc in blocked}: owner.line_check.open_list()
        snapshot = [(doc, rows) for doc, rows, report in checked if not report.structural]
        if not snapshot:return None
    missing_sources = [d['path'] for d, _ in snapshot if not Path(d['path']).is_file()]
    if mode != 'custom' and missing_sources:
        QMessageBox.warning(owner, 'Đường dẫn nguồn không còn hợp lệ', 'Không xuất tự động cạnh đường dẫn cũ. Chọn thư mục thay thế.\n'+'\n'.join(missing_sources))
        mode = 'custom'
    if mode == 'custom':
        root = QFileDialog.getExistingDirectory(owner, 'Thư mục xuất thay thế', store.setting('bulk_export_root'))
        if not root: return None
    missing = sum(workspace_status(rows)['missing'] for _, rows in snapshot)
    if missing and QMessageBox.question(owner, 'Bản dịch chưa hoàn chỉnh', f'Bản dịch còn {missing} dòng chưa hoàn thành.\nChỉ xuất bản nháp với suffix INCOMPLETE? Nội dung nguồn thay thế vẫn phải qua kiểm tra ngôn ngữ; tài liệu có đoạn nguồn sai ngôn ngữ đích sẽ bị chặn.', QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return None
    try: plan = plan_exports(snapshot, root, mode=mode)
    except ValueError as exc:
        QMessageBox.warning(owner, 'Không thể xuất', str(exc)); return None
    paths = '\n'.join(str(p['target']) for p in plan)
    if QMessageBox.question(owner, 'Xác nhận đường dẫn xuất', paths, QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return None
    policy = 'cancel'
    if any(p['target'].exists() for p in plan):
        selected, ok = QInputDialog.getItem(owner, 'File đích đã tồn tại', 'Áp dụng cho các file đích trùng:', ['Lưu phiên bản mới', 'Ghi đè', 'Hủy'], 0, False)
        if not ok or selected == 'Hủy': return None
        policy = 'version' if selected == 'Lưu phiên bản mới' else 'overwrite'
    store.set_setting('export_mode', mode)
    if root: store.set_setting('bulk_export_root', root)
    return plan, policy
