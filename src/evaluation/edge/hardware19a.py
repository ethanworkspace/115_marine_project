"""Read-only Windows/NVIDIA measurements with explicit memory scopes."""
from __future__ import annotations
import ctypes as C
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from .runtime import system_ram


def gpu_sample():
    fields=['name','memory.total','driver_version','utilization.gpu','memory.used','temperature.gpu','power.draw','clocks.gr','clocks.mem']
    text=subprocess.check_output(['nvidia-smi','-i','0','--query-gpu='+','.join(fields),
        '--format=csv,noheader,nounits'],text=True,timeout=5).strip()
    cells=dict(zip(fields,[v.strip() for v in text.split(',')],strict=True))
    def number(k):
        try:return float(cells[k])
        except (ValueError,TypeError):return None
    return dict(name=cells['name'],dedicated_total_bytes=int(number('memory.total')*1024**2),
        driver_version=cells['driver_version'],utilization_percent=number('utilization.gpu'),
        dedicated_used_bytes=int(number('memory.used')*1024**2) if number('memory.used') is not None else None,
        temperature_c=number('temperature.gpu'),gpu_board_power_watts=number('power.draw'),
        graphics_clock_mhz=number('clocks.gr'),memory_clock_mhz=number('clocks.mem'),raw=cells)


def validate_identity(capture,gpu,version):
    failures=[]
    cpu=capture['CPU'];mods=capture['memory_modules']
    if 'i5-14400F' not in cpu['Name'] or cpu['NumberOfCores']!=10 or cpu['NumberOfLogicalProcessors']!=16:
        failures.append('CPU mismatch')
    if sum(m['Capacity'] for m in mods)!=32*1024**3 or any(m['Speed']!=3200 or m['SMBIOSMemoryType']!=26 for m in mods):
        failures.append('32 GiB DDR4-3200 physical modules mismatch')
    if gpu['name']!='NVIDIA GeForce RTX 4060' or not 8000*1024**2<=gpu['dedicated_total_bytes']<=8192*1024**2:
        failures.append('GPU / dedicated VRAM mismatch')
    if capture['GPU']['DriverVersion']!='32.0.16.1088':failures.append('GPU driver mismatch')
    if 'Windows 11' not in capture['OS']['Caption']:failures.append('OS mismatch')
    if version!='0.35.0':failures.append('Ollama version mismatch')
    if capture['computer']['Name']!=platform.node():failures.append('execution host mismatch')
    if failures:raise ValueError('; '.join(failures))
    return dict(matched=True,checks=['CPU','cores','threads','physical_RAM','DDR4','memory_speed','GPU','dedicated_VRAM','OS','driver','runtime','execution_node'],
        physical_RAM_bytes=sum(m['Capacity'] for m in mods),OS_usable_RAM_bytes=capture['computer']['TotalPhysicalMemory'],
        VRAM_scope='dedicated, driver-reported usable capacity; shared capacity is separate')


class ProcessEntry(C.Structure):
    _fields_=[('dwSize',C.c_ulong),('cntUsage',C.c_ulong),('th32ProcessID',C.c_ulong),
        ('th32DefaultHeapID',C.c_size_t),('th32ModuleID',C.c_ulong),('cntThreads',C.c_ulong),
        ('th32ParentProcessID',C.c_ulong),('pcPriClassBase',C.c_long),('dwFlags',C.c_ulong),('szExeFile',C.c_wchar*260)]


class ProcessMemory(C.Structure):
    _fields_=[('cb',C.c_ulong),('PageFaultCount',C.c_ulong)]+[(k,C.c_size_t) for k in
        ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
         'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage','PrivateUsage')]


def ollama_working_sets():
    k=C.WinDLL('kernel32',use_last_error=True);p=C.WinDLL('psapi',use_last_error=True)
    k.CreateToolhelp32Snapshot.restype=C.c_void_p;k.CloseHandle.argtypes=[C.c_void_p]
    k.Process32FirstW.argtypes=[C.c_void_p,C.POINTER(ProcessEntry)];k.Process32NextW.argtypes=k.Process32FirstW.argtypes
    k.OpenProcess.argtypes=[C.c_ulong,C.c_int,C.c_ulong];k.OpenProcess.restype=C.c_void_p
    p.GetProcessMemoryInfo.argtypes=[C.c_void_p,C.POINTER(ProcessMemory),C.c_ulong]
    snap=k.CreateToolhelp32Snapshot(2,0)
    if snap==C.c_void_p(-1).value:raise OSError('process enumeration unavailable')
    rows=[]
    try:
        e=ProcessEntry();e.dwSize=C.sizeof(e);ok=k.Process32FirstW(snap,C.byref(e))
        while ok:
            if e.szExeFile.casefold().startswith('ollama'):
                h=k.OpenProcess(0x1000|0x10,False,e.th32ProcessID)
                m=ProcessMemory();m.cb=C.sizeof(m)
                row=dict(pid=e.th32ProcessID,name=e.szExeFile,working_set_bytes=None,private_commit_bytes=None)
                if h:
                    if p.GetProcessMemoryInfo(h,C.byref(m),m.cb):row.update(working_set_bytes=m.WorkingSetSize,private_commit_bytes=m.PrivateUsage)
                    k.CloseHandle(h)
                rows.append(row)
            ok=k.Process32NextW(snap,C.byref(e))
    finally:k.CloseHandle(snap)
    return rows


class PdhValue(C.Structure):
    _fields_=[('status',C.c_ulong),('value',C.c_double)]
class PdhItem(C.Structure):
    _fields_=[('name',C.c_wchar_p),('value',PdhValue)]


class GpuMemoryCounters:
    """Native PDH wildcard arrays; retain adapter identity, never call shared VRAM."""
    def __init__(self):
        self.dll=C.WinDLL('pdh');self.query=C.c_void_p();self.handles={};self.errors=[]
        d=self.dll
        d.PdhOpenQueryW.argtypes=[C.c_wchar_p,C.c_size_t,C.POINTER(C.c_void_p)]
        d.PdhAddEnglishCounterW.argtypes=[C.c_void_p,C.c_wchar_p,C.c_size_t,C.POINTER(C.c_void_p)]
        d.PdhCollectQueryData.argtypes=[C.c_void_p]
        d.PdhGetFormattedCounterArrayW.argtypes=[C.c_void_p,C.c_ulong,C.POINTER(C.c_ulong),C.POINTER(C.c_ulong),C.c_void_p]
        d.PdhCloseQuery.argtypes=[C.c_void_p]
        if d.PdhOpenQueryW(None,0,C.byref(self.query)):raise OSError('PDH query unavailable')
        for key,path in {'shared_adapter':r'\GPU Adapter Memory(*)\Shared Usage',
                         'dedicated_process':r'\GPU Process Memory(*)\Dedicated Usage',
                         'shared_process':r'\GPU Process Memory(*)\Shared Usage'}.items():
            h=C.c_void_p();status=d.PdhAddEnglishCounterW(self.query,path,0,C.byref(h))
            if status:self.errors.append(key+': '+str(status))
            else:self.handles[key]=h
        d.PdhCollectQueryData(self.query)

    def sample(self):
        self.dll.PdhCollectQueryData(self.query);result={}
        for key,h in self.handles.items():
            size=C.c_ulong();count=C.c_ulong()
            self.dll.PdhGetFormattedCounterArrayW(h,0x200,C.byref(size),C.byref(count),None)
            if not size.value:result[key]=None;continue
            buf=C.create_string_buffer(size.value)
            status=self.dll.PdhGetFormattedCounterArrayW(h,0x200,C.byref(size),C.byref(count),buf)
            if status:result[key]=None;continue
            items=C.cast(buf,C.POINTER(PdhItem))
            result[key]=[dict(instance=items[i].name,value_bytes=items[i].value.value) for i in range(count.value)
                if items[i].value.status in (0,1)]
        return result

    def close(self):self.dll.PdhCloseQuery(self.query)


class Sensors:
    def __init__(self):
        self.errors=[];self.previous_CPU_times=None
        try:self.pdh=GpuMemoryCounters()
        except Exception as exc:self.pdh=None;self.errors.append(str(exc))

    def sample(self):
        r=dict(timestamp=time.monotonic(),wall_timestamp=time.time(),system_RAM_used_bytes=None,
            ollama_process_working_sets=None,GPU_process_memory=None,shared_GPU_memory=None,gpu=None,CPU_utilization_percent=None)
        try:
            idle=C.c_ulonglong();kernel=C.c_ulonglong();user=C.c_ulonglong()
            if C.windll.kernel32.GetSystemTimes(C.byref(idle),C.byref(kernel),C.byref(user)):
                current=(idle.value,kernel.value+user.value)
                if self.previous_CPU_times:
                    di=current[0]-self.previous_CPU_times[0];dt=current[1]-self.previous_CPU_times[1]
                    r['CPU_utilization_percent']=100*(1-di/dt) if dt else None
                self.previous_CPU_times=current
        except Exception as e:self.errors.append(str(e))
        try:r['system_RAM_used_bytes']=system_ram()[0]
        except Exception as e:self.errors.append(str(e))
        try:r['ollama_process_working_sets']=ollama_working_sets()
        except Exception as e:self.errors.append(str(e))
        try:r['gpu']=gpu_sample()
        except Exception as e:self.errors.append(str(e))
        if self.pdh:
            try:
                data=self.pdh.sample();r['shared_GPU_memory']=data.get('shared_adapter')
                pids={v['pid'] for v in r['ollama_process_working_sets'] or []}
                r['GPU_process_memory']={key:[v for v in data.get(key) or [] if any(v['instance'].startswith('pid_'+str(pid)+'_') for pid in pids)]
                    if data.get(key) is not None else None for key in ('dedicated_process','shared_process')}
            except Exception as e:self.errors.append(str(e))
        r['memory_scopes']={'system_RAM':'whole_system_used','Ollama_working_set':'per_process; family sum may double-count shared pages',
            'GPU_dedicated':'whole_GPU_device','GPU_process':'Ollama family per WDDM adapter instance',
            'shared_GPU':'WDDM adapter instances, system RAM-backed; not dedicated VRAM'}
        return r

    def close(self):
        if self.pdh:self.pdh.close()
