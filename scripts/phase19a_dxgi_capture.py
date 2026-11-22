"""Read-only DXGI adapter identity/capacity for labeling measured WDDM instances."""
import ctypes as C,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.evaluation.edge.execution19a import OUT,write
class GUID(C.Structure):
    _fields_=[('a',C.c_ulong),('b',C.c_ushort),('c',C.c_ushort),('d',C.c_ubyte*8)]
class LUID(C.Structure):_fields_=[('low',C.c_ulong),('high',C.c_long)]
class Desc(C.Structure):
    _fields_=[('Description',C.c_wchar*128)]+[(k,C.c_uint) for k in ('VendorId','DeviceId','SubSysId','Revision')]+[
        (k,C.c_size_t) for k in ('DedicatedVideoMemory','DedicatedSystemMemory','SharedSystemMemory')]+[('AdapterLuid',LUID),('Flags',C.c_uint)]
def method(obj,index,restype,*args):
    table=C.cast(obj,C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(restype,C.c_void_p,*args)(table[index])
def main():
    factory=C.c_void_p();guid=GUID(0x7b7166ec,0x21c7,0x44ae,(C.c_ubyte*8)(0xb2,0x1a,0xc9,0xae,0x32,0x1a,0xe3,0x69))
    create=C.WinDLL('dxgi').CreateDXGIFactory1;create.argtypes=[C.POINTER(GUID),C.POINTER(C.c_void_p)];create.restype=C.c_long
    result=[];errors=[]
    try:
        status=create(C.byref(guid),C.byref(factory))
        if status:raise OSError('CreateDXGIFactory1 HRESULT '+hex(status&0xffffffff))
        enum=method(factory,12,C.c_long,C.c_uint,C.POINTER(C.c_void_p))
        for i in range(8):
            adapter=C.c_void_p();status=enum(factory,i,C.byref(adapter))
            if status&0xffffffff==0x887a0002:break
            if status:raise OSError('EnumAdapters1 failed '+hex(status&0xffffffff))
            try:
                d=Desc();status=method(adapter,10,C.c_long,C.POINTER(Desc))(adapter,C.byref(d))
                if status:raise OSError('GetDesc1 failed')
                prefix=f'luid_0x{d.AdapterLuid.high&0xffffffff:08X}_0x{d.AdapterLuid.low:08X}'
                result.append(dict(name=d.Description,LUID_instance_prefix=prefix,dedicated_video_capacity_bytes=d.DedicatedVideoMemory,
                    shared_system_capacity_bytes=d.SharedSystemMemory,dedicated_system_capacity_bytes=d.DedicatedSystemMemory,flags=d.Flags,
                    memory_scope='DXGI-reported capacities, not measured inference usage; shared is RAM-backed, separate from dedicated'))
            finally:method(adapter,2,C.c_ulong)(adapter)
    except Exception as exc:errors.append(str(exc))
    finally:
        if factory:method(factory,2,C.c_ulong)(factory)
    write(OUT/'dxgi_adapter_identity.json',dict(adapters=result,errors=errors,read_only=True));print(json.dumps({'adapters':result,'errors':errors},ensure_ascii=False))
if __name__=='__main__':main()
