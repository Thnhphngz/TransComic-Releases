"""Stable locale identities shared by UI, prompts, storage and export."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Language:
    locale: str
    name: str
    prompt: str
    code: str
    folder: str
    script: str = 'Latin'

LANGUAGES = (
    Language('vi','Tiếng Việt','Vietnamese','VI','Vietnamese'),
    Language('en','Tiếng Anh','English','EN','English'),
    Language('id','Tiếng Indonesia','Indonesian — Bahasa Indonesia','ID','Indonesian'),
    Language('hi','Tiếng Hindi','Hindi — हिन्दी','HI','Hindi','Devanagari'),
    Language('de','Tiếng Đức','German — Deutsch','DE','German'),
    Language('ms','Tiếng Malay','Malay — Bahasa Melayu, not Indonesian','MS','Malay'),
    Language('ja','Tiếng Nhật','Japanese — 日本語','JA','Japanese','Japanese'),
    Language('zh-CN','Tiếng Trung giản thể','Simplified Chinese — 简体中文, simplified characters','ZH-CN','Simplified-Chinese','Han'),
    Language('fil','Tiếng Filipino','Filipino — Filipino/Tagalog, not Indonesian','FIL','Filipino'),
    Language('en-CA','Tiếng Anh Canada','Canadian English — English (Canada)','EN-CA','Canadian-English'),
    Language('fr-CA','Tiếng Pháp Canada','Canadian French — Français canadien','FR-CA','Canadian-French'),
)
LANG_CODES = {l.name:l.code for l in LANGUAGES}

def language(value):
    if value == 'Tiếng Trung': value='zh-CN'  # Existing history alias.
    for entry in LANGUAGES:
        if str(value).casefold() in {v.casefold() for v in (entry.locale,entry.name,entry.code,entry.folder,entry.prompt,entry.prompt.split(' — ')[0])}: return entry
    raise ValueError('Unsupported language: '+str(value))

def validate_pair(source,target):
    a,b=language(source),language(target)
    if a.locale==b.locale: raise ValueError('Source and target must differ')
    return a,b

def export_name(path,target,incomplete=False):
    from pathlib import Path
    p=Path(path); entry=language(target)
    return p.stem+'_'+entry.code+('_INCOMPLETE' if incomplete else '')+p.suffix.lower()
