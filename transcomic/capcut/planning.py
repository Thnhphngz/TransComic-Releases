"""Pure, ordered group partitioning shared by preview and background export."""
from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class ProjectPart:
    name: str
    start: int
    end: int
    groups: tuple


def partition_groups(groups,count):
    groups=tuple(groups)
    if type(count) is not int or not 2<=count<=len(groups):
        raise ValueError('Số project phải là số nguyên từ 2 đến tổng số nhóm')
    quotient,remainder=divmod(len(groups),count);cursor=0;parts=[]
    for i in range(count):
        size=quotient+(i<remainder);parts.append(groups[cursor:cursor+size]);cursor+=size
    return tuple(parts)


def name_errors(parts):
    """Strict names: the exporter must not silently sanitize custom input."""
    errors={};seen={}
    for i,part in enumerate(parts,1):
        name=part.name
        if not isinstance(name,str):errors[i]='Tên project phải là văn bản.';continue
        if not name.strip():errors[i]='Tên project không được rỗng.'
        elif name!=name.strip() or name.startswith('.') or name.endswith('.'):errors[i]='Tên không được bắt đầu/kết thúc bằng khoảng trắng hoặc dấu chấm.'
        elif len(name)>80:errors[i]='Tên project tối đa 80 ký tự; hãy rút gọn tên.'
        elif re.search(r'[<>:"/\\|?*\x00-\x1f]',name):errors[i]='Tên chứa ký tự không hợp lệ trong tên thư mục Windows.'
        elif re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])',name.split('.')[0].rstrip(' '),re.I):errors[i]='Tên dành riêng của Windows không được sử dụng.'
        key=unicodedata.normalize('NFC',name).casefold()
        if key in seen:
            errors[i]=f'Tên trùng với part {seen[key]} (không phân biệt hoa/thường).'
            errors[seen[key]]=f'Tên trùng với part {i} (không phân biệt hoa/thường).'
        else:seen[key]=i
    return errors


def project_plan(groups,mode,name='TransComic',part_count=2,custom_names=None,*,validate=True):
    from .exporter import safe_name
    groups=tuple(groups)
    if mode!='split':raise ValueError('Kế hoạch chia yêu cầu chế độ split')
    base=safe_name(name);cursor=1;result=[]
    for i,part in enumerate(partition_groups(groups,part_count),1):
        suffix=f'_part{i}';part_name=base[:80-len(suffix)].rstrip(' .')+suffix
        part_name=(custom_names or {}).get(str(i),part_name)
        result.append(ProjectPart(part_name,cursor,cursor+len(part)-1,part));cursor+=len(part)
    errors=name_errors(result)
    if validate and errors:raise ValueError(' · '.join(f'Part {i}: {text}' for i,text in errors.items()))
    return tuple(result)
