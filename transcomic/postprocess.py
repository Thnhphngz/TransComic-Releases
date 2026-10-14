"""Deterministic normalization of NEW API text, never manual edits or sources."""
import re
from .quality import PLACEHOLDER

VERSION = 'review-periods-v2-technical-links'


def normalize(source, raw):
    protected = []
    def protect(match):
        protected.append(match.group())
        return '\x00' + str(len(protected)-1) + '\x00'
    text = PLACEHOLDER.sub(protect, raw)
    def protect_link(match):
        link=match.group().rstrip('.,!?;:')
        protected.append(link)
        return '\x00'+str(len(protected)-1)+'\x00'+match.group()[len(link):]
    text = re.sub(r'https?://[^\s<>"\x00]+|www\.[^\s<>"\x00]+',protect_link,text)
    text = re.sub(r'\b\d{2}:\d{2}:\d{2}[.,]\d{3}\b', protect, text)
    notes = []
    text = re.sub(r'\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr)\.(?:\s*)', r'\1 ', text, flags=re.I)
    # Decimal/domain/initial separators become spaces; sentence separators commas.
    text = re.sub(r'(?<=\w)\.(?=\w)', ' ', text)
    text = re.sub(r'\.+(["”»]+)\s+(?=\w)', r'\1, ', text)
    text = re.sub(r'\.+(?=["”»]*\s*$)', '', text)
    text = re.sub(r'\.+(?=\s*[^\s\x00])', ', ', text)
    text = re.sub(r'\.+', '', text)
    text = re.sub(r' +', ' ', text).strip()
    for i, token in enumerate(protected):
        text = text.replace('\x00'+str(i)+'\x00', token)
        if '.' in token:
            notes.append('Protected token conflicts with period rule: preserved')
    if sorted(PLACEHOLDER.findall(source)) != sorted(PLACEHOLDER.findall(text)):
        notes.append('Placeholder mismatch')
    quote = r'["“”«»]'
    if len(re.findall(quote, raw)) > len(re.findall(quote, source)):
        notes.append('New quotation marks: review manually')
    if len(re.findall(r'[.!?]+', raw)) > len(re.findall(r'[.!?]+', source)):
        notes.append('Additional sentence segments: review manually')
    return text, notes
