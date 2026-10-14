"""Native no-follow reparse reads/restores; never traverses or removes targets."""
import ctypes
from ctypes import wintypes as W
import struct

def kernel():
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,ctypes.c_void_p,W.DWORD,W.DWORD,W.HANDLE];k.CreateFileW.restype=W.HANDLE
    k.DeviceIoControl.argtypes=[W.HANDLE,W.DWORD,ctypes.c_void_p,W.DWORD,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p]
    k.CloseHandle.argtypes=[W.HANDLE]
    return k
def control(path,code,blob=None,share=7):
    k=kernel();handle=k.CreateFileW(str(path),0x40000000 if blob else 0,share,None,3,0x02200000,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        output=ctypes.create_string_buffer(16384);size=W.DWORD();data=ctypes.create_string_buffer(blob) if blob else None
        if not k.DeviceIoControl(handle,code,data,len(blob) if blob else 0,None if blob else output,0 if blob else len(output),ctypes.byref(size),None):raise ctypes.WinError(ctypes.get_last_error())
        return output.raw[:size.value]
    finally:k.CloseHandle(handle)
def read(path,exclusive=False):
    blob=control(path,0x900A8,share=0 if exclusive else 7);tag,length=struct.unpack_from('<IH',blob)
    if len(blob)!=length+8 or tag not in (0xA0000003,0xA000000C):raise ValueError('Unknown reparse format')
    offset,n,print_offset,print_n=struct.unpack_from('<HHHH',blob,8)
    start=16 if tag==0xA0000003 else 20
    if start+offset+n>len(blob) or start+print_offset+print_n>len(blob):raise ValueError('Invalid reparse bounds')
    return {'tag':tag,'kind':'junction' if tag==0xA0000003 else 'symlink','raw_hex':blob.hex(),
            'substitute_name':blob[start+offset:start+offset+n].decode('utf-16-le'),
            'print_name':blob[start+print_offset:start+print_offset+print_n].decode('utf-16-le')}
def restore_junction(path,raw_hex):
    blob=bytes.fromhex(raw_hex)
    if struct.unpack_from('<I',blob)[0]!=0xA0000003:raise ValueError('Only mount-point fixture restore supported')
    # New empty directory, opened with OPEN_REPARSE_POINT. No unlink/rmtree.
    path.mkdir();control(path,0x900A4,blob)
    if read(path)['raw_hex']!=raw_hex:raise ValueError('Restored reparse mismatch')
