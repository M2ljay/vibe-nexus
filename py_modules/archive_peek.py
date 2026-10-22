"""List what is inside a remote .zip or .7z without downloading it.

Nexus publishes a file listing for most uploads, but not all: Halloween's
newer files all came back empty (2026-10-20), so the mod check could say
nothing about them. Both formats keep their table of contents at the end
(zip's central directory; 7z's header, often LZMA-packed), so a few ranged
reads - usually tens of KB - give every path in the archive.

`fetch(offset, length) -> bytes` is supplied by the caller (an HTTP Range
request); `size` is the archive's total length. Pure Python, stdlib only.
RAR keeps a header before each file, spread through the whole archive, so
it isn't handled here (None).
"""

from __future__ import annotations

import io
import lzma
import struct
import zipfile

MAX_FETCH = 12 << 20  # never read more than this from one archive
SEVEN_SIG = b"7z\xbc\xaf\x27\x1c"
ZIP_SIG = b"PK"


class TooMuch(Exception):
    pass


class RangeReader(io.RawIOBase):
    """A seekable file over fetch(), reading 64 KB blocks and keeping them."""

    BLOCK = 64 << 10

    def __init__(self, fetch, size: int, block: int = 0):
        self._fetch, self._size, self._pos = fetch, size, 0
        if block:
            self.BLOCK = block
        self._blocks: dict = {}
        self.fetched = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, off, whence=0):
        self._pos = off if whence == 0 else self._pos + off if whence == 1 else self._size + off
        self._pos = max(0, min(self._pos, self._size))
        return self._pos

    def _block(self, n: int) -> bytes:
        if n not in self._blocks:
            start = n * self.BLOCK
            length = min(self.BLOCK, self._size - start)
            self.fetched += length
            if self.fetched > MAX_FETCH:
                raise TooMuch()
            self._blocks[n] = self._fetch(start, length)
        return self._blocks[n]

    def read(self, n=-1):
        if n is None or n < 0:
            n = self._size - self._pos
        out = bytearray()
        while n > 0 and self._pos < self._size:
            b, o = divmod(self._pos, self.BLOCK)
            chunk = self._block(b)[o:o + n]
            if not chunk:
                break
            out += chunk
            self._pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, buf):
        data = self.read(len(buf))
        buf[:len(data)] = data
        return len(data)


def zip_listing(reader) -> list:
    with zipfile.ZipFile(reader) as z:
        return [i.filename for i in z.infolist() if not i.is_dir()]


# ---- 7z ----------------------------------------------------------------------
K_END, K_HEADER, K_ARCHIVE_PROPS, K_ADD_STREAMS, K_MAIN_STREAMS, K_FILES = 0, 1, 2, 3, 4, 5
K_PACK, K_UNPACK, K_SUBSTREAMS, K_SIZE, K_CRC, K_FOLDER, K_UNPACK_SIZE = 6, 7, 8, 9, 10, 11, 12
K_NUM_UNPACK, K_EMPTY_STREAM, K_EMPTY_FILE, K_NAME, K_ENCODED = 13, 14, 15, 17, 23


class _Buf:
    def __init__(self, data: bytes):
        self.d, self.i = data, 0

    def byte(self) -> int:
        v = self.d[self.i]
        self.i += 1
        return v

    def take(self, n: int) -> bytes:
        v = self.d[self.i:self.i + n]
        if len(v) < n:
            raise ValueError("7z header cut short")
        self.i += n
        return v

    def num(self) -> int:
        first = self.byte()
        mask, value = 0x80, 0
        for n in range(8):
            if not first & mask:
                return value | ((first & (mask - 1)) << (8 * n))
            value |= self.byte() << (8 * n)
            mask >>= 1
        return value

    def bits(self, n: int) -> list:
        out, cur, mask = [], 0, 0
        for _ in range(n):
            if not mask:
                cur, mask = self.byte(), 0x80
            out.append(bool(cur & mask))
            mask >>= 1
        return out

    def defined(self, n: int) -> list:
        return [True] * n if self.byte() else self.bits(n)


def _digests(b: _Buf, n: int) -> list:
    d = b.defined(n)
    for flag in d:
        if flag:
            b.take(4)
    return d


def _streams_info(b: _Buf) -> dict:
    info = {"pack_pos": 0, "pack_sizes": [], "folders": [], "unpack_sizes": [], "crc_defined": []}
    t = b.byte()
    if t == K_PACK:
        info["pack_pos"] = b.num()
        n = b.num()
        t = b.byte()
        while t != K_END:
            if t == K_SIZE:
                info["pack_sizes"] = [b.num() for _ in range(n)]
            elif t == K_CRC:
                _digests(b, n)
            t = b.byte()
        t = b.byte()
    if t == K_UNPACK:
        if b.byte() != K_FOLDER:
            raise ValueError("7z: no folders")
        nf = b.num()
        if b.byte():
            raise ValueError("7z: external folders")
        for _ in range(nf):
            coders, total_in, total_out = [], 0, 0
            for _c in range(b.num()):
                flags = b.byte()
                cid = b.take(flags & 0x0F)
                nin, nout = (b.num(), b.num()) if flags & 0x10 else (1, 1)
                props = b.take(b.num()) if flags & 0x20 else b""
                coders.append((cid, props))
                total_in, total_out = total_in + nin, total_out + nout
            for _p in range(total_out - 1):
                b.num(), b.num()
            packed = total_in - (total_out - 1)
            if packed > 1:
                for _p in range(packed):
                    b.num()
            info["folders"].append({"coders": coders, "outs": total_out})
        if b.byte() != K_UNPACK_SIZE:
            raise ValueError("7z: no unpack sizes")
        for f in info["folders"]:
            f["sizes"] = [b.num() for _ in range(f["outs"])]
            info["unpack_sizes"].append(f["sizes"][-1])
        t = b.byte()
        info["crc_defined"] = [False] * nf
        while t != K_END:
            if t == K_CRC:
                info["crc_defined"] = _digests(b, nf)
            t = b.byte()
        t = b.byte()
    if t == K_SUBSTREAMS:
        nf = len(info["folders"])
        per = [1] * nf
        t = b.byte()
        if t == K_NUM_UNPACK:
            per = [b.num() for _ in range(nf)]
            t = b.byte()
        if t == K_SIZE:
            for n in per:
                for _ in range(max(0, n - 1)):
                    b.num()
            t = b.byte()
        crcs = info["crc_defined"] or [False] * nf
        nd = sum(n for n, known in zip(per, crcs) if not (n == 1 and known))
        while t != K_END:
            if t == K_CRC:
                _digests(b, nd)
            else:
                b.take(b.num())
            t = b.byte()
        t = b.byte()
    if t != K_END:
        raise ValueError("7z: streams info not ended")
    return info


def _unpack_header(info: dict, fetch_abs) -> bytes:
    """The real header, out of an encoded (LZMA / LZMA2) one."""
    if len(info["folders"]) != 1 or len(info["folders"][0]["coders"]) != 1:
        raise ValueError("7z: header not plain LZMA")
    cid, props = info["folders"][0]["coders"][0]
    size = info["unpack_sizes"][0]
    packed = fetch_abs(32 + info["pack_pos"], info["pack_sizes"][0])
    if cid == b"\x03\x01\x01":
        d = props[0]
        lc, d = d % 9, d // 9
        lp, pb = d % 5, d // 5
        filt = {"id": lzma.FILTER_LZMA1, "lc": lc, "lp": lp, "pb": pb,
                "dict_size": max(int.from_bytes(props[1:5], "little"), 4096)}
    elif cid == b"\x21":
        p = props[0]
        filt = {"id": lzma.FILTER_LZMA2, "dict_size": min((2 | (p & 1)) << (p // 2 + 11), 1 << 30)}
    else:
        raise ValueError("7z: header packed with an unknown method (encrypted?)")
    out = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=[filt]).decompress(packed, size)
    if len(out) < size:
        raise ValueError("7z: header didn't unpack")
    return out[:size]


def _files(b: _Buf) -> list:
    n = b.num()
    names, empty_stream, empty_file = [], [False] * n, []
    while True:
        t = b.byte()
        if t == K_END:
            break
        size = b.num()
        data = _Buf(b.take(size))
        if t == K_EMPTY_STREAM:
            empty_stream = data.bits(n)
        elif t == K_EMPTY_FILE:
            empty_file = data.bits(sum(empty_stream))
        elif t == K_NAME:
            if data.byte():
                raise ValueError("7z: external names")
            raw = data.d[data.i:]
            names = raw.decode("utf-16-le").split("\x00")[:n]
    out, k = [], 0
    for i, name in enumerate(names):
        is_dir = False
        if empty_stream[i]:
            is_dir = not (empty_file[k] if k < len(empty_file) else False)
            k += 1
        if not is_dir:
            out.append(name.replace("\\", "/"))
    return out


def seven_listing(fetch_abs, size: int) -> list:
    start = fetch_abs(0, 32)
    if start[:6] != SEVEN_SIG:
        raise ValueError("not 7z")
    off, length = struct.unpack("<QQ", start[12:28])
    if length > MAX_FETCH or 32 + off + length > size:
        raise TooMuch()
    header = fetch_abs(32 + off, length)
    for _ in range(3):  # encoded headers can nest; 7-Zip writes one level
        b = _Buf(header)
        t = b.byte()
        if t == K_HEADER:
            break
        if t != K_ENCODED:
            raise ValueError("7z: unknown header")
        header = _unpack_header(_streams_info(b), fetch_abs)
    b = _Buf(header)
    if b.byte() != K_HEADER:
        raise ValueError("7z: no header")
    t = b.byte()
    if t == K_ARCHIVE_PROPS:
        while b.byte() != K_END:
            b.take(b.num())
        t = b.byte()
    if t == K_ADD_STREAMS:
        _streams_info(b)
        t = b.byte()
    if t == K_MAIN_STREAMS:
        _streams_info(b)
        t = b.byte()
    if t == K_FILES:
        return _files(b)
    return []


# ---- RAR ---------------------------------------------------------------------
# A header sits before each file, and each says how much data follows it, so
# the headers can be visited one by one, skipping the data between them.
RAR5_SIG = b"Rar!\x1a\x07\x01\x00"
RAR4_SIG = b"Rar!\x1a\x07\x00"
MAX_RAR_BLOCKS = 4000


def _vint(b: bytes, i: int) -> tuple:
    value, shift = 0, 0
    while True:
        if i >= len(b):
            raise ValueError("rar: header cut short")
        c = b[i]
        i += 1
        value |= (c & 0x7F) << shift
        if not c & 0x80:
            return value, i
        shift += 7
        if shift > 63:
            raise ValueError("rar: bad number")


def rar5_listing(read_at, size: int) -> list:
    out, pos = [], len(RAR5_SIG)
    for _ in range(MAX_RAR_BLOCKS):
        if pos + 7 > size:
            break
        head = read_at(pos, 16)
        hsize, i = _vint(head, 4)
        if hsize <= 0 or hsize > 1 << 21:
            raise ValueError("rar: bad header size")
        start = i  # header data begins after CRC and the size field
        block = read_at(pos + start, hsize)
        htype, j = _vint(block, 0)
        hflags, j = _vint(block, j)
        if htype == 4:
            raise ValueError("rar: encrypted headers")
        if hflags & 0x01:
            _extra, j = _vint(block, j)
        data_size = 0
        if hflags & 0x02:
            data_size, j = _vint(block, j)
        if htype == 2:  # file
            fflags, j = _vint(block, j)
            _unp, j = _vint(block, j)
            _attr, j = _vint(block, j)
            if fflags & 0x02:
                j += 4
            if fflags & 0x04:
                j += 4
            _comp, j = _vint(block, j)
            _host, j = _vint(block, j)
            nlen, j = _vint(block, j)
            name = block[j:j + nlen].decode("utf-8", "replace")
            if not fflags & 0x01:  # not a directory
                out.append(name.replace("\\", "/"))
        elif htype == 5:  # end of archive
            break
        pos = pos + start + hsize + data_size
    else:
        raise TooMuch()
    return out


def rar4_listing(read_at, size: int) -> list:
    out, pos = [], len(RAR4_SIG)
    for _ in range(MAX_RAR_BLOCKS):
        if pos + 7 > size:
            break
        head = read_at(pos, 7)
        _crc, htype, flags, hsize = struct.unpack("<HBHH", head)
        if hsize < 7:
            raise ValueError("rar: bad header")
        add = 0
        if htype == 0x73 and flags & 0x80:
            raise ValueError("rar: encrypted headers")
        if htype == 0x74:  # file
            block = read_at(pos, hsize)
            pack, _unp, _host, _crc2, _time, _ver, _meth, nlen, _attr = struct.unpack(
                "<IIBIIBBHI", block[7:32])
            off = 32
            if flags & 0x100:
                pack |= struct.unpack("<I", block[32:36])[0] << 32
                off = 40
            raw = block[off:off + nlen].split(b"\x00")[0]
            try:
                name = raw.decode("utf-8")
            except UnicodeDecodeError:
                name = raw.decode("cp437")
            if (flags & 0xE0) != 0xE0:
                out.append(name.replace("\\", "/"))
            add = pack
        elif flags & 0x8000:
            add = struct.unpack("<I", read_at(pos + 7, 4))[0]
        if htype == 0x7B:
            break
        pos += hsize + add
    else:
        raise TooMuch()
    return out


def listing(fetch, size: int):
    """Every file path in the archive, or None when it can't be read this way."""
    if size <= 0:
        return None
    reader = RangeReader(fetch, size)
    try:
        head = reader.read(8)
        if head[:6] == SEVEN_SIG:
            def fetch_abs(o, n):
                reader.seek(o)
                return reader.read(n)
            return seven_listing(fetch_abs, size)
        if head[:2] == ZIP_SIG:
            return zip_listing(reader)
        if head[:2] == b"MZ":
            # A self-extracting archive: the stub is a program, the rest an
            # archive. Zip finds itself from the end; 7z/RAR start after it.
            reader.seek(0)
            stub = reader.read(1 << 20)
            import installers
            off = installers.sfx_offset(stub)
            if off is not None:
                return listing(lambda o, n: fetch(o + off, n), size - off)
            try:
                return zip_listing(reader)
            except zipfile.BadZipFile:
                return None
        if head[:7] == RAR4_SIG or head[:8] == RAR5_SIG:
            small = RangeReader(fetch, size, block=8 << 10)

            def read_at(o, n):
                small.seek(o)
                return small.read(n)
            return (rar5_listing if head[:8] == RAR5_SIG else rar4_listing)(read_at, size)
    except (TooMuch, ValueError, zipfile.BadZipFile, lzma.LZMAError, struct.error,
            IndexError, UnicodeDecodeError, EOFError, OSError):
        return None
    return None


def is_rar(head: bytes) -> bool:
    return head.startswith(b"Rar!\x1a\x07")
