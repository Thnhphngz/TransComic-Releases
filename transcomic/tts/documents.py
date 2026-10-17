"""Source snapshots and literal sentence splitting; no source files are changed."""
import os
from pathlib import Path
import re
from bisect import bisect_right
from ..documents import import_txt
from ..docx_document import import_docx


def read_document(path,encoding=None):
    path=Path(path).resolve()
    if path.suffix.lower()=='.txt':
        data=import_txt(path,encoding);lines=[x.text for x in data.lines];locators=[str(i+1) for i in range(len(lines))]
    elif path.suffix.lower()=='.docx':
        data=import_docx(path);lines=[x.text for x in data.units];locators=[x.locator for x in data.units]
    else:raise ValueError('Chỉ hỗ trợ TXT/DOCX')
    return dict(name=path.stem,path=str(path),text='\n'.join(lines),locators=locators,line_count=len(lines))


def scan(paths):
    result=[];seen=set();errors=[]
    def add(path):
        key=os.path.normcase(str(path.resolve()))
        if key not in seen and path.suffix.lower() in ('.txt','.docx'):
            seen.add(key);result.append(path)
    for item in paths:
        path=Path(item)
        if path.is_file():add(path)
        elif path.is_dir():
            for current,dirs,files in os.walk(path,followlinks=False):
                dirs[:]=sorted(d for d in dirs if not (Path(current)/d).is_symlink() and not getattr((Path(current)/d).lstat(),'st_file_attributes',0)&0x400)
                for name in sorted(files):
                    file=Path(current)/name
                    if not file.is_symlink():add(file)
        else:errors.append((str(path),'Không tìm thấy đường dẫn'))
    return result,errors


def segments(text,mode='lines'):
    # combined remains readable for immutable historical snapshots only.
    if mode not in ('lines','sentences','combined','none'):raise ValueError('Chế độ tách không hợp lệ')
    boundaries=[0]
    if mode in ('lines','combined'):boundaries.extend(m.end() for m in re.finditer(r'\r\n|\r|\n',text))
    if mode in ('sentences','combined'):boundaries.extend(m.end() for m in re.finditer(r'[.!?。！？]+',text))
    boundaries=sorted(set([*boundaries,len(text)]));result=[]
    line_ends=[m.end() for m in re.finditer(r'\r\n|\r|\n',text)]
    for start,end in zip(boundaries,boundaries[1:]):
        raw=text[start:end];left=len(raw)-len(raw.lstrip());right=len(raw.rstrip())
        start+=left;end=start+max(0,right-left)
        value=text[start:end]
        if not value or not any(c.isalnum() for c in value):continue
        result.append(dict(text=value,start=start,end=end,line_start=bisect_right(line_ends,start)+1,
                           line_end=bisect_right(line_ends,end)+1))
    return result


def mismatch(text,language):
    if language not in ('ja','cmn') and re.search(r'[\u3040-\u30ff\u4e00-\u9fff]',text):return 'Văn bản có chữ Nhật/Trung, không khớp ngôn ngữ giọng đã chọn.'
    if language not in ('hi',) and re.search(r'[\u0900-\u097f]',text):return 'Văn bản có chữ Devanagari, có thể không khớp giọng.'
    if re.search('[ăâđêôơưĂÂĐÊÔƠƯ]',text):return 'Kokoro v1.0 không hỗ trợ tiếng Việt; không đảm bảo phát âm văn bản này.'
    return ''
