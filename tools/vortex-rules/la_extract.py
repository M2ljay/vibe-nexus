"""Extract any archive libarchive reads (7z, rar, zip) via ctypes.
Usage: python3 -I la_extract.py <archive> <dest>"""
import ctypes
import os
import sys

lib = ctypes.CDLL("libarchive.so.13")
lib.archive_read_new.restype = ctypes.c_void_p
lib.archive_read_support_format_all.argtypes = [ctypes.c_void_p]
lib.archive_read_support_filter_all.argtypes = [ctypes.c_void_p]
lib.archive_read_open_filename.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
lib.archive_read_next_header.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
lib.archive_entry_pathname.argtypes = [ctypes.c_void_p]
lib.archive_entry_pathname.restype = ctypes.c_char_p
lib.archive_entry_filetype.argtypes = [ctypes.c_void_p]
lib.archive_read_data.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
lib.archive_read_data.restype = ctypes.c_ssize_t
lib.archive_read_free.argtypes = [ctypes.c_void_p]


def extract(src, dest):
    a = lib.archive_read_new()
    lib.archive_read_support_format_all(a)
    lib.archive_read_support_filter_all(a)
    if lib.archive_read_open_filename(a, src.encode(), 10240) != 0:
        raise SystemExit("cannot open")
    entry = ctypes.c_void_p()
    buf = ctypes.create_string_buffer(65536)
    dest_abs = os.path.abspath(dest)
    while lib.archive_read_next_header(a, ctypes.byref(entry)) == 0:
        name = (lib.archive_entry_pathname(entry) or b"").decode("utf-8", "replace").replace("\\", "/")
        if lib.archive_entry_filetype(entry) != 0o100000 or not name:
            continue
        out = os.path.abspath(os.path.join(dest, name))
        if not out.startswith(dest_abs + os.sep):
            continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            while True:
                n = lib.archive_read_data(a, buf, len(buf))
                if n <= 0:
                    break
                f.write(buf.raw[:n])
    lib.archive_read_free(a)


extract(sys.argv[1], sys.argv[2])
