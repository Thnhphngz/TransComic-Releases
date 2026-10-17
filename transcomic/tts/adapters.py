"""DXGI adapter order matches ONNX Runtime DirectML device_id.

Inventory is only a preference; inference/profiling must still prove GPU use.
"""
import sys


def adapters():
    if sys.platform!='win32':return []
    import ctypes as c
    from uuid import UUID
    class GUID(c.Structure):_fields_=[('data',c.c_ubyte*16)]
    class LUID(c.Structure):_fields_=[('low',c.c_uint32),('high',c.c_int32)]
    class DESC(c.Structure):
        _fields_=[('description',c.c_wchar*128),('vendor',c.c_uint32),('device',c.c_uint32),('subsystem',c.c_uint32),('revision',c.c_uint32),
                  ('dedicated',c.c_size_t),('system',c.c_size_t),('shared',c.c_size_t),('luid',LUID),('flags',c.c_uint32)]
    def method(pointer,index,result,*args):
        table=c.cast(pointer,c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(result,c.c_void_p,*args)(table[index])
    factory=c.c_void_p();result=[]
    try:
        create=c.windll.dxgi.CreateDXGIFactory1;create.argtypes=[c.POINTER(GUID),c.POINTER(c.c_void_p)];create.restype=c.c_long
        iid=GUID();iid.data[:]=UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le
        if create(c.byref(iid),c.byref(factory))<0:return []
        enum=method(factory,12,c.c_long,c.c_uint32,c.POINTER(c.c_void_p))
        for index in range(16):
            adapter=c.c_void_p()
            if enum(factory,index,c.byref(adapter))<0:break
            try:
                desc=DESC()
                if method(adapter,10,c.c_long,c.POINTER(DESC))(adapter,c.byref(desc))>=0 and not desc.flags&2:
                    result.append(dict(id=index,name=desc.description,vendor=desc.vendor,dedicated_bytes=desc.dedicated))
            finally:method(adapter,2,c.c_ulong)(adapter)
    except (OSError,AttributeError):return []
    finally:
        if factory.value:method(factory,2,c.c_ulong)(factory)
    return result


def preferred_device():
    available=adapters()
    return max(available,key=lambda item:item['dedicated_bytes'])['id'] if available else 0
