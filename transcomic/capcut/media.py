"""Positional natural/creation-time matching and immutable, source-fenced media snapshots."""
from dataclasses import dataclass
from pathlib import Path
import math
import os
import re
import unicodedata
import uuid
import wave

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImageReader

IMAGES=frozenset(('.png','.jpg','.jpeg','.webp'))
AUDIO=frozenset(('.wav','.mp3'))


class Cancelled(Exception):pass


def checkpoint(cancel):
    if cancel and cancel.is_set():raise Cancelled('Đã hủy')


def native_path(path,force=False):
    """Extended Windows I/O paths; never changes system long-path policy."""
    text=os.path.abspath(path)
    if os.name=='nt' and (force or len(text)>=240) and not text.startswith('\\\\?\\'):
        text='\\\\?\\UNC\\'+text[2:] if text.startswith('\\\\') else '\\\\?\\'+text
    return Path(text)


def natural_key(name):
    return tuple((0,int(p)) if p.isdigit() else (1,p.casefold()) for p in re.split(r'(\d+)',unicodedata.normalize('NFC',str(name))))


def numeric_id(name):
    numbers=re.findall(r'\d+',unicodedata.normalize('NFC',Path(name).stem))
    return int(numbers[0]) if len(numbers)==1 and len(numbers[0])<=12 else None


@dataclass(frozen=True)
class MediaGroup:
    id: str
    name: str
    image_dir: str
    audio_dir: str
    image_sort: str="name"

    @classmethod
    def create(cls,name,image_dir,audio_dir,image_sort="name"):
        return cls(str(uuid.uuid4()),name.strip() or 'Nhóm media',str(native_path(image_dir)),str(native_path(audio_dir)),image_sort)


@dataclass(frozen=True)
class MediaFile:
    path: str
    size: int
    mtime_ns: int
    duration_us: int=0
    width: int=0
    height: int=0
    error: str=''
    created_ns: int | None=None

    def unchanged(self):
        try:
            s=Path(self.path).stat()
            return s.st_size==self.size and s.st_mtime_ns==self.mtime_ns and Path(self.path).is_file()
        except OSError:return False


@dataclass(frozen=True)
class MediaPair:
    id: str
    group_id: str
    number: int | None
    images: tuple[MediaFile,...]
    audios: tuple[MediaFile,...]
    errors: tuple[str,...]

    @property
    def valid(self):return not self.errors and len(self.images)==len(self.audios)==1
    @property
    def duration_us(self):return self.audios[0].duration_us if len(self.audios)==1 else 0


@dataclass(frozen=True)
class GroupScan:
    group: MediaGroup
    rows: tuple[MediaPair,...]
    errors: tuple[str,...]=()

    @property
    def valid(self):return bool(self.rows) and not self.errors and all(r.valid for r in self.rows)
    @property
    def matched(self):return sum(r.valid for r in self.rows)
    @property
    def error_count(self):return len(self.errors)+sum(bool(r.errors) for r in self.rows)
    @property
    def image_count(self):return sum(not f.error for r in self.rows for f in r.images)
    @property
    def audio_count(self):return sum(not f.error for r in self.rows for f in r.audios)


def audio_duration(path):
    path=Path(path)
    if path.suffix.lower()=='.wav':
        with wave.open(str(path),'rb') as w:
            frames,rate=w.getnframes(),w.getframerate()
            if frames<=0 or rate<=0:raise ValueError('Audio rỗng')
            # Check the final frame as well: a truncated WAV header is not enough.
            w.setpos(frames-1)
            if len(w.readframes(1))!=w.getnchannels()*w.getsampwidth():raise ValueError('WAV bị cắt')
            return (frames*1_000_000+rate//2)//rate
    if path.suffix.lower()=='.mp3':
        from mutagen.mp3 import MP3
        info=MP3(path).info
        if info.sketchy or not math.isfinite(info.length) or info.length<=0:raise ValueError('MP3 không hợp lệ')
        return max(1,round(info.length*1_000_000))
    raise ValueError('Chỉ hỗ trợ WAV/MP3')


def creation_time_ns(stat):
    value=getattr(stat,'st_birthtime_ns',None)
    if value is None and os.name=='nt':value=round(stat.st_ctime*1_000_000_000)
    return value if isinstance(value,int) and value>0 else None


def probe(path,image):
    path=native_path(path).resolve()
    try:
        st=path.stat()
        if not path.is_file() or st.st_size==0:raise ValueError('File rỗng hoặc không tồn tại')
        if path.suffix.lower() not in (IMAGES if image else AUDIO):raise ValueError('Sai định dạng')
        if image:
            reader=QImageReader(str(path));reader.setAutoTransform(True)
            size=reader.size()
            if not size.isValid():raise ValueError('Ảnh không đọc được')
            reader.setScaledSize(size.scaled(QSize(256,256),Qt.KeepAspectRatio))
            if reader.read().isNull():raise ValueError('Ảnh hỏng')
            media=MediaFile(str(path),st.st_size,st.st_mtime_ns,width=size.width(),height=size.height(),created_ns=creation_time_ns(st))
        else:media=MediaFile(str(path),st.st_size,st.st_mtime_ns,duration_us=audio_duration(path))
        if not media.unchanged():raise ValueError('File thay đổi trong khi kiểm tra')
        return media
    except Exception as exc:
        # No fallback duration; unexpected decoder errors also block this file.
        return MediaFile(str(path),0,0,error=str(exc) or type(exc).__name__)


def scan_group(group,cancel=None,progress=None):
    errors=[];sides=[]
    if group.image_sort not in ('name','created'):raise ValueError('Chế độ sắp ảnh không hợp lệ')
    for image,folder in ((True,group.image_dir),(False,group.audio_dir)):
        checkpoint(cancel);media=[]
        try:
            root=native_path(folder)
            if not root.is_dir():raise ValueError('Thư mục không tồn tại')
            # Direct children of the explicitly selected folder, of this media
            # kind only. Parent audio and subfolders cannot enter image rows.
            paths=[p for p in root.iterdir() if not p.is_dir() and p.suffix.lower() in (IMAGES if image else AUDIO)]
            paths.sort(key=lambda p:(natural_key(p.name),os.path.normcase(str(p.absolute())),str(p.absolute())))
            seen=set()
            for i,path in enumerate(paths):
                checkpoint(cancel)
                key=os.path.normcase(str(path.resolve()))
                if key in seen:errors.append('Đường dẫn bị liệt kê trùng: '+str(path));continue
                seen.add(key)
                if progress:progress(f'Kiểm tra {group.name}: {path.name}',i+1,len(paths))
                media.append(probe(path,image))
            if not media:errors.append(('Ảnh' if image else 'Audio')+': thư mục không có media hợp lệ')
        except (OSError,ValueError) as exc:
            errors.append(('Ảnh' if image else 'Audio')+': '+str(exc))
        if image and group.image_sort=='created':
            if any(f.created_ns is None for f in media):errors.append('Không lấy được Date created đáng tin cậy; không dùng Date modified thay thế')
            media.sort(key=lambda f:(f.created_ns is None,f.created_ns or 0,natural_key(Path(f.path).name),os.path.normcase(f.path),f.path))
        sides.append(media)
    images,audios=sides;mismatch=len(images)!=len(audios)
    if mismatch:errors.append(f'Số lượng không bằng nhau: {len(images)} ảnh / {len(audios)} audio. Mọi cặp theo vị trí cần kiểm tra lại; không thể xuất.')
    rows=[]
    for index in range(max(len(images),len(audios))):
        im=tuple(images[index:index+1]);au=tuple(audios[index:index+1]);issues=[]
        if not im:issues.append('Thiếu ảnh')
        if not au:issues.append('Thiếu audio')
        if mismatch:issues.append('Chưa xác nhận ghép: số lượng lệch')
        issues.extend(f.error for f in im+au if f.error)
        # Stable pair identity is based on both original paths, not a widget
        # position or the order in which probing completes.
        identity=uuid.uuid5(uuid.NAMESPACE_URL,group.id+'\n'+'\n'.join(f.path for f in im+au))
        rows.append(MediaPair(str(identity),group.id,index+1,im,au,tuple(issues)))
    return GroupScan(group,tuple(rows),tuple(errors))


def freeze(scans):
    """Group order and each verified positional pair order are the only timeline order."""
    scans=tuple(scans)
    if not scans or any(not s.valid for s in scans):raise ValueError('Có nhóm chưa kiểm tra hoặc có lỗi; không thể xuất')
    if len({s.group.id for s in scans})!=len(scans):raise ValueError('Trùng ID nhóm')
    pairs=tuple(p for s in scans for p in s.rows)
    if len({p.id for p in pairs})!=len(pairs):raise ValueError('Trùng ID cặp')
    return pairs
