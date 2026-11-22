"""Read-only Windows process-tree memory capture, including llama-server runners."""
import ctypes as C
import os
import platform

from .core19b import process_roles


def windows_process_tree(benchmark_pid=None, reranker_pid=None):
    if platform.system() != 'Windows':
        return {'available': False, 'reason': 'Windows process telemetry unavailable', 'processes': []}
    from .hardware19a import ProcessEntry, ProcessMemory
    kernel = C.WinDLL('kernel32', use_last_error=True)
    psapi = C.WinDLL('psapi', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [C.c_ulong, C.c_ulong]
    kernel.CreateToolhelp32Snapshot.restype = C.c_void_p
    kernel.CloseHandle.argtypes = [C.c_void_p]
    kernel.OpenProcess.argtypes = [C.c_ulong, C.c_int, C.c_ulong]
    kernel.OpenProcess.restype = C.c_void_p
    kernel.Process32FirstW.argtypes = [C.c_void_p, C.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = kernel.Process32FirstW.argtypes
    psapi.GetProcessMemoryInfo.argtypes = [C.c_void_p, C.POINTER(ProcessMemory), C.c_ulong]
    snap = kernel.CreateToolhelp32Snapshot(2, 0)
    if snap == C.c_void_p(-1).value:
        return {'available': False, 'reason': 'Process snapshot failed', 'processes': []}
    rows = []
    try:
        entry = ProcessEntry(); entry.dwSize = C.sizeof(entry)
        ok = kernel.Process32FirstW(snap, C.byref(entry))
        while ok:
            rows.append({'pid': int(entry.th32ProcessID), 'parent_pid': int(entry.th32ParentProcessID),
                         'name': entry.szExeFile})
            ok = kernel.Process32NextW(snap, C.byref(entry))
    finally:
        kernel.CloseHandle(snap)
    selected = process_roles(rows, benchmark_pid or os.getpid(), reranker_pid)
    for row in selected:
        row.update(working_set_bytes=None, private_commit_bytes=None, process_GPU_memory_bytes=None)
        handle = kernel.OpenProcess(0x1000 | 0x10, False, row['pid'])
        if not handle:
            row['memory_error'] = 'Process memory access unavailable'
            continue
        try:
            memory = ProcessMemory(); memory.cb = C.sizeof(memory)
            if psapi.GetProcessMemoryInfo(handle, C.byref(memory), memory.cb):
                row.update(working_set_bytes=int(memory.WorkingSetSize), private_commit_bytes=int(memory.PrivateUsage))
            else:
                row['memory_error'] = 'Process memory query failed'
        finally:
            kernel.CloseHandle(handle)
    return {'available': True, 'processes': selected, 'total_process_count': len(rows),
            'scope': 'Per-process Windows working set and private commit; not summed into dedicated VRAM',
            'unobserved_process_memory': None}
