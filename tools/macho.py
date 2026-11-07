"""Minimal Mach-O x86_64 parser: segments, sections, symbols, function starts,
dyld rebase/bind opcodes and indirect symbol tables."""
import struct

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x2
LC_DYSYMTAB = 0xB
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_FUNCTION_STARTS = 0x26
LC_DATA_IN_CODE = 0x29
LC_MAIN = 0x80000028
LC_LOAD_DYLIB = 0xC
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_REEXPORT_DYLIB = 0x8000001F
LC_LAZY_LOAD_DYLIB = 0x20
LC_LOAD_UPWARD_DYLIB = 0x80000023
LC_ID_DYLIB = 0xD

CPU_TYPE_X86_64 = 0x01000007


class Section:
    def __init__(self, segname, sectname, addr, size, offset, flags, r1, r2):
        self.segname, self.sectname = segname, sectname
        self.addr, self.size, self.offset = addr, size, offset
        self.flags, self.reserved1, self.reserved2 = flags, r1, r2

    @property
    def type(self):
        return self.flags & 0xFF

    def __repr__(self):
        return f"<{self.segname},{self.sectname} {self.addr:#x}+{self.size:#x}>"


class Segment:
    def __init__(self, name, vmaddr, vmsize, fileoff, filesize, maxprot, initprot):
        self.name, self.vmaddr, self.vmsize = name, vmaddr, vmsize
        self.fileoff, self.filesize = fileoff, filesize
        self.maxprot, self.initprot = maxprot, initprot
        self.sections = []


def read_uleb(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            return r, i


def read_sleb(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        s += 7
        if c < 0x80:
            if c & 0x40:
                r -= 1 << s
            return r, i


def slice_x86_64(data):
    """Return (offset, size) of the x86_64 slice of a fat or thin file."""
    magic = struct.unpack_from(">I", data, 0)[0]
    if magic in (0xCAFEBABE, 0xCAFEBABF):
        n = struct.unpack_from(">I", data, 4)[0]
        wide = magic == 0xCAFEBABF
        for k in range(n):
            if wide:
                ct, st, off, sz, al, _ = struct.unpack_from(">iiQQII", data, 8 + k * 32)
            else:
                ct, st, off, sz, al = struct.unpack_from(">iiIII", data, 8 + k * 20)
            if ct == CPU_TYPE_X86_64:
                return off, sz
        raise ValueError("no x86_64 slice")
    return 0, len(data)


class MachO:
    def __init__(self, path):
        raw = open(path, "rb").read()
        off, size = slice_x86_64(raw)
        self.data = d = raw[off:off + size]
        magic, cpu, sub, ftype, ncmds, sizeofcmds, flags, _ = struct.unpack_from("<IiiIIIII", d, 0)
        assert magic == 0xFEEDFACF and cpu == CPU_TYPE_X86_64
        self.segments, self.sections, self.dylibs = [], [], []
        self.entryoff = None
        self.symoff = self.nsyms = self.stroff = self.strsize = 0
        self.dysym = None
        self.dyld_info = None
        self.func_starts_off = self.func_starts_size = 0
        self.dic_off = self.dic_size = 0
        self.install_name = None
        p = 32
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from("<II", d, p)
            if cmd == LC_SEGMENT_64:
                segname = d[p + 8:p + 24].rstrip(b"\0").decode()
                vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, _ = struct.unpack_from("<QQQQiiII", d, p + 24)
                seg = Segment(segname, vmaddr, vmsize, fileoff, filesize, maxprot, initprot)
                q = p + 72
                for _ in range(nsects):
                    sn = d[q:q + 16].rstrip(b"\0").decode()
                    gn = d[q + 16:q + 32].rstrip(b"\0").decode()
                    addr, ssize, soff, align, reloff, nreloc, sflags, r1, r2, _ = struct.unpack_from("<QQIIIIIIII", d, q + 32)
                    s = Section(gn, sn, addr, ssize, soff, sflags, r1, r2)
                    s.align = align
                    seg.sections.append(s)
                    self.sections.append(s)
                    q += 80
                self.segments.append(seg)
            elif cmd == LC_SYMTAB:
                self.symoff, self.nsyms, self.stroff, self.strsize = struct.unpack_from("<IIII", d, p + 8)
            elif cmd == LC_DYSYMTAB:
                self.dysym = struct.unpack_from("<18I", d, p + 8)
            elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
                self.dyld_info = struct.unpack_from("<10I", d, p + 8)
            elif cmd == LC_FUNCTION_STARTS:
                self.func_starts_off, self.func_starts_size = struct.unpack_from("<II", d, p + 8)
            elif cmd == LC_DATA_IN_CODE:
                self.dic_off, self.dic_size = struct.unpack_from("<II", d, p + 8)
            elif cmd == LC_MAIN:
                self.entryoff = struct.unpack_from("<Q", d, p + 8)[0]
            elif cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB, LC_LOAD_UPWARD_DYLIB):
                noff = struct.unpack_from("<I", d, p + 8)[0]
                self.dylibs.append(d[p + noff:p + cmdsize].split(b"\0")[0].decode())
            elif cmd == LC_ID_DYLIB:
                noff = struct.unpack_from("<I", d, p + 8)[0]
                self.install_name = d[p + noff:p + cmdsize].split(b"\0")[0].decode()
            p += cmdsize
        self.base = next(s.vmaddr for s in self.segments if s.name == "__TEXT")
        self._symbols = None

    # ---- address helpers -------------------------------------------------
    def section(self, seg, sect):
        for s in self.sections:
            if s.segname == seg and s.sectname == sect:
                return s
        return None

    def sections_named(self, seg, sect):
        return [s for s in self.sections if s.segname == seg and s.sectname == sect]

    def segment(self, name):
        return next((s for s in self.segments if s.name == name), None)

    def addr_to_off(self, addr):
        for s in self.segments:
            if s.vmaddr <= addr < s.vmaddr + s.filesize:
                return s.fileoff + (addr - s.vmaddr)
        return None

    def read(self, addr, n):
        o = self.addr_to_off(addr)
        if o is None:
            return b"\0" * n
        return self.data[o:o + n]

    def u64(self, addr):
        return struct.unpack("<Q", self.read(addr, 8))[0]

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def cstr(self, addr):
        o = self.addr_to_off(addr)
        if o is None:
            return None
        e = self.data.index(b"\0", o)
        return self.data[o:e].decode("utf-8", "replace")

    # ---- symbols ---------------------------------------------------------
    def symbols(self):
        """List of (name, n_type, n_sect, n_desc, n_value)."""
        if self._symbols is None:
            d = self.data
            out = []
            for i in range(self.nsyms):
                strx, ntype, nsect, ndesc, nvalue = struct.unpack_from("<IBBHQ", d, self.symoff + i * 16)
                e = d.index(b"\0", self.stroff + strx)
                out.append((d[self.stroff + strx:e].decode("utf-8", "replace"), ntype, nsect, ndesc, nvalue))
            self._symbols = out
        return self._symbols

    def defined_symbols(self):
        """addr -> name for symbols defined in this image (N_SECT, not stabs)."""
        m = {}
        for name, ntype, nsect, ndesc, nvalue in self.symbols():
            if ntype & 0xE0:
                continue
            if (ntype & 0x0E) == 0x0E:
                m.setdefault(nvalue, name)
        return m

    def function_starts(self):
        d = self.data
        i, end = self.func_starts_off, self.func_starts_off + self.func_starts_size
        addr = self.base
        out = []
        while i < end:
            v, i = read_uleb(d, i)
            if v == 0:
                break
            addr += v
            out.append(addr)
        return out

    def data_in_code(self):
        d = self.data
        out = []
        for k in range(self.dic_size // 8):
            off, length, kind = struct.unpack_from("<IHH", d, self.dic_off + k * 8)
            out.append((self.base + off, length, kind))
        return out

    def indirect_symbols(self):
        """For each pointer/stub section: list of (slot_addr, symbol name or None)."""
        return [(s, a, n) for s, a, n, _ in self.indirect_symbols_ex()]

    def indirect_symbols_ex(self):
        """indirect_symbols() plus each symbol's two-level library ordinal (None if local)."""
        d = self.data
        indirectsymoff, nindirect = self.dysym[12], self.dysym[13]
        syms = self.symbols()
        out = []
        for s in self.sections:
            t = s.type
            if t in (6, 7):  # non-lazy / lazy symbol pointers
                stride = 8
            elif t == 8:  # symbol stubs
                stride = s.reserved2
            else:
                continue
            for k in range(s.size // stride):
                idx = struct.unpack_from("<I", d, indirectsymoff + (s.reserved1 + k) * 4)[0]
                if idx & 0xC0000000:
                    out.append((s, s.addr + k * stride, None, None))
                    continue
                name, ntype, _, ndesc, _ = syms[idx]
                # A defined symbol behind a stub is the image's own (interposable) export.
                ordinal = (ndesc >> 8) & 0xFF if (ntype & 0x0E) == 0 else 0
                out.append((s, s.addr + k * stride, name, ordinal))
        return out

    # ---- dyld info -------------------------------------------------------
    def rebases(self):
        """List of pointer addresses that need sliding."""
        rebase_off, rebase_size = self.dyld_info[0], self.dyld_info[1]
        d = self.data
        i, end = rebase_off, rebase_off + rebase_size
        segs = self.segments
        addr = 0
        typ = 0
        out = []
        while i < end:
            b = d[i]
            i += 1
            op, imm = b & 0xF0, b & 0x0F
            if op == 0x00:
                break
            elif op == 0x10:
                typ = imm
            elif op == 0x20:
                o, i = read_uleb(d, i)
                addr = segs[imm].vmaddr + o
            elif op == 0x30:
                o, i = read_uleb(d, i)
                addr = (addr + o) & 0xFFFFFFFFFFFFFFFF
            elif op == 0x40:
                addr += imm * 8
            elif op == 0x50:
                for _ in range(imm):
                    out.append(addr)
                    addr += 8
            elif op == 0x60:
                n, i = read_uleb(d, i)
                for _ in range(n):
                    out.append(addr)
                    addr += 8
            elif op == 0x70:
                out.append(addr)
                o, i = read_uleb(d, i)
                addr = (addr + 8 + o) & 0xFFFFFFFFFFFFFFFF
            elif op == 0x80:
                n, i = read_uleb(d, i)
                skip, i = read_uleb(d, i)
                for _ in range(n):
                    out.append(addr)
                    addr += 8 + skip
            else:
                raise ValueError(f"bad rebase op {b:#x}")
        return out

    def _binds(self, off, size, lazy=False):
        d = self.data
        i, end = off, off + size
        segs = self.segments
        addr = 0
        ordinal = 0
        name = None
        addend = 0
        flags = 0
        out = []
        while i < end:
            b = d[i]
            i += 1
            op, imm = b & 0xF0, b & 0x0F
            if op == 0x00:
                if lazy:
                    continue
                break
            elif op == 0x10:
                ordinal = imm
            elif op == 0x20:
                ordinal, i = read_uleb(d, i)
            elif op == 0x30:
                ordinal = -imm if imm else 0
                if imm:
                    ordinal = (imm | 0xF0) - 256
            elif op == 0x40:
                flags = imm
                e = d.index(b"\0", i)
                name = d[i:e].decode()
                i = e + 1
            elif op == 0x50:
                pass
            elif op == 0x60:
                addend, i = read_sleb(d, i)
            elif op == 0x70:
                o, i = read_uleb(d, i)
                addr = segs[imm].vmaddr + o
            elif op == 0x80:
                o, i = read_uleb(d, i)
                addr = (addr + o) & 0xFFFFFFFFFFFFFFFF
            elif op == 0x90:
                out.append((addr, name, ordinal, addend, flags))
                addr += 8
            elif op == 0xA0:
                out.append((addr, name, ordinal, addend, flags))
                o, i = read_uleb(d, i)
                addr = (addr + 8 + o) & 0xFFFFFFFFFFFFFFFF
            elif op == 0xB0:
                out.append((addr, name, ordinal, addend, flags))
                addr += 8 + imm * 8
            elif op == 0xC0:
                n, i = read_uleb(d, i)
                skip, i = read_uleb(d, i)
                for _ in range(n):
                    out.append((addr, name, ordinal, addend, flags))
                    addr += 8 + skip
            else:
                raise ValueError(f"bad bind op {b:#x}")
        return out

    def binds(self):
        di = self.dyld_info
        return self._binds(di[2], di[3])

    def weak_binds(self):
        di = self.dyld_info
        return self._binds(di[4], di[5])

    def lazy_binds(self):
        di = self.dyld_info
        return self._binds(di[6], di[7], lazy=True)

    def exports(self):
        """name -> (flags, address)."""
        d = self.data
        start, size = self.dyld_info[8], self.dyld_info[9]
        out = {}
        stack = [(start, "")]
        while stack:
            node, prefix = stack.pop()
            i = node
            tsize, i = read_uleb(d, i)
            if tsize:
                j = i
                fl, j = read_uleb(d, j)
                if fl & 0x08:
                    ordv, j = read_uleb(d, j)
                    out[prefix] = (fl, None)
                else:
                    a, j = read_uleb(d, j)
                    out[prefix] = (fl, self.base + a)
            i += tsize
            nchild = d[i]
            i += 1
            for _ in range(nchild):
                e = d.index(b"\0", i)
                edge = d[i:e].decode("utf-8", "replace")
                i = e + 1
                co, i = read_uleb(d, i)
                stack.append((start + co, prefix + edge))
        return out


class Merged:
    """Main executable plus private dylibs as one guest image.

    Each library is placed at its own slide; its rebased pointers are slid, and
    pointer slots bound to symbols another merged image exports become internal
    pointers (reported as rebases), so the tools see a single statically linked
    program.  Calls through stubs to such symbols are listed in stub_targets.

    A library may name symbols it defines that must stay native (libc++abi inside a
    guest libc++: exception state and typeinfo must be the runtime's).  Every
    reference to them, from any image, then binds to the native symbol:
    pointers become binds, and code addresses are listed in native_alias.
    """

    def __init__(self, main_path, libs):
        self.main = MachO(main_path)
        self.images = [(self.main, 0, set(), ())] + [(MachO(p), sl, set(nat), tuple(rp)) for p, sl, nat, rp in libs]
        self.base = self.main.base
        self.entryoff = self.main.entryoff
        self.dylibs = self.main.dylibs
        self.install_name = None
        by_name = {}
        for i, (img, sl, nat, rp) in enumerate(self.images):
            for nm in ((img.install_name,) if img.install_name else ()) + rp:
                by_name[nm] = i
                by_name[nm.rsplit("/", 1)[-1]] = i
        self._by_name = by_name
        self._exports = []
        self._hidden = []  # sorted [(start, end, name)] of native-only definitions, slid
        self._nat = [nat for img, sl, nat, rp in self.images]
        for img, sl, nat, rp in self.images:
            ex = img.exports()
            self._exports.append({n: (fl, a + sl if a is not None else None) for n, (fl, a) in ex.items()
                                  if n not in nat})
            bounds = sorted(set(a for a in img.defined_symbols()) | set(a for fl, a in ex.values() if a is not None))
            import bisect
            for n, (fl, a) in ex.items():
                if n in nat and a is not None:
                    j = bisect.bisect_right(bounds, a)
                    end = bounds[j] if j < len(bounds) else a + 8
                    self._hidden.append((a + sl, end + sl, n))
        self._hidden.sort()
        self._hidden_lo = [h[0] for h in self._hidden]
        self.native_alias = {lo: n for lo, hi, n in self._hidden}
        self.images = [(img, sl) for img, sl, nat, rp in self.images]
        self.segments, self.sections, self._ranges = [], [], []
        self._secmap = {}
        for i, (img, sl) in enumerate(self.images):
            for g in img.segments:
                if g.name == "__PAGEZERO":
                    continue
                ng = Segment(g.name, g.vmaddr + sl, g.vmsize, g.fileoff, g.filesize, g.maxprot, g.initprot)
                for s in g.sections:
                    ns = Section(s.segname, s.sectname, s.addr + sl, s.size, s.offset, s.flags, s.reserved1, s.reserved2)
                    ns.align, ns.image = s.align, i
                    ng.sections.append(ns)
                    self.sections.append(ns)
                    self._secmap[(i, id(s))] = ns
                self.segments.append(ng)
                self._ranges.append((ng.vmaddr, ng.vmaddr + ng.filesize, i, g))
        self._ranges.sort(key=lambda r: r[0])
        self._resolve()

    # ---- symbol resolution across images --------------------------------
    def _lib_index(self, i, ordinal, name):
        """Merged image a bind of image i resolves into, or None for a system library."""
        img = self.images[i][0]
        if ordinal is None:
            return None
        if ordinal == 0:  # this image's own (interposable) definition
            return i if name in self._exports[i] else None
        if ordinal > 0:
            path = img.dylibs[ordinal - 1] if ordinal <= len(img.dylibs) else ""
            j = self._by_name.get(path, self._by_name.get(path.rsplit("/", 1)[-1]))
            return j if j is not None and j != i else None
        if ordinal == 0xFF or ordinal == -1:  # main executable
            return 0
        if ordinal == 0xFE or ordinal == -2:  # flat lookup
            return next((j for j, ex in enumerate(self._exports) if j != i and name in ex), None)
        return None

    def _target(self, i, ordinal, name, addend=0):
        j = self._lib_index(i, ordinal, name)
        if j is None:
            return None
        e = self._exports[j].get(name)
        if not e or e[1] is None:
            if name in self._nat[j] or e:  # stays native, or re-exported from a system library
                return None
            raise ValueError(f"{name} not exported by {self.images[j][0].install_name}")
        return e[1] + addend

    def hidden_at(self, addr):
        """(native symbol, delta) if addr lies in a definition that stays native."""
        import bisect
        k = bisect.bisect_right(self._hidden_lo, addr) - 1
        if k >= 0:
            lo, hi, n = self._hidden[k]
            if lo <= addr < hi:
                return n, addr - lo
        return None

    def _resolve(self):
        self._patched = []
        self._rebases, self._binds, self._lazy, self._weak = [], [], [], []
        self.stub_targets = {}
        self._indirect = []
        for i, (img, sl) in enumerate(self.images):
            d = bytearray(img.data)

            def put(addr, v):
                struct.pack_into("<Q", d, img.addr_to_off(addr), v & 0xFFFFFFFFFFFFFFFF)

            for r in img.rebases():
                v = struct.unpack_from("<Q", d, img.addr_to_off(r))[0] + sl
                h = self.hidden_at(v)
                if h:
                    self._binds.append((r + sl, h[0], 0, h[1], 0))
                    continue
                put(r, v)
                self._rebases.append(r + sl)
            for lst, out in ((img.binds(), self._binds), (img.lazy_binds(), self._lazy)):
                for a, n, o, add, fl in lst:
                    t = self._target(i, o, n, add)
                    if t is None:
                        out.append((a + sl, n, o, add, fl))
                    else:
                        put(a, t)
                        self._rebases.append(a + sl)
            self._weak += [(a + sl, n, o, add, fl) for a, n, o, add, fl in img.weak_binds()]
            for s, a, n, o in img.indirect_symbols_ex():
                ns = self._secmap[(i, id(s))]
                t = self._target(i, o, n) if n else None
                if t is not None:
                    if s.type == 8:
                        self.stub_targets[a + sl] = t
                    n = None
                self._indirect.append((ns, a + sl, n))
            self._patched.append(bytes(d))

    # ---- MachO interface ------------------------------------------------
    def _at(self, addr):
        import bisect
        k = bisect.bisect_right([r[0] for r in self._ranges], addr) - 1
        if k >= 0:
            lo, hi, i, g = self._ranges[k]
            if lo <= addr < hi:
                return i, g.fileoff + (addr - lo)
        return None, None

    def section(self, seg, sect):
        return next((s for s in self.sections if s.segname == seg and s.sectname == sect), None)

    def sections_named(self, seg, sect):
        return [s for s in self.sections if s.segname == seg and s.sectname == sect]

    def segment(self, name):
        return next((s for s in self.segments if s.name == name), None)

    def read(self, addr, n):
        i, o = self._at(addr)
        if i is None:
            return b"\0" * n
        return self._patched[i][o:o + n]

    def u64(self, addr):
        return struct.unpack("<Q", self.read(addr, 8))[0]

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def cstr(self, addr):
        i, o = self._at(addr)
        if i is None:
            return None
        d = self._patched[i]
        return d[o:d.index(b"\0", o)].decode("utf-8", "replace")

    def defined_symbols(self):
        out = {}
        for img, sl in self.images:
            for a, n in img.defined_symbols().items():
                out.setdefault(a + sl, n)
        return out

    def function_starts(self):
        return [a + sl for img, sl in self.images for a in img.function_starts()]

    def data_in_code(self):
        return [(a + sl, l, k) for img, sl in self.images for a, l, k in img.data_in_code()]

    def indirect_symbols(self):
        return list(self._indirect)

    def rebases(self):
        return list(self._rebases)

    def binds(self):
        return list(self._binds)

    def lazy_binds(self):
        return list(self._lazy)

    def weak_binds(self):
        return list(self._weak)

    def exports(self):
        return dict(self._exports[0])


def tbd_symbols(path):
    """Exported symbol names listed in a text-based stub (.tbd)."""
    import re
    text = open(path).read()
    out = set()
    for m in re.finditer(r"(?:symbols|weak-symbols|thread-local-symbols):\s*\[([^\]]*)\]", text):
        out.update(x.strip().strip("'") for x in m.group(1).split(",") if x.strip())
    for m in re.finditer(r"objc-(?:classes|eh-types):\s*\[([^\]]*)\]", text):
        for x in m.group(1).split(","):
            x = x.strip().strip("'")
            if x:
                out.update((f"_OBJC_CLASS_$_{x}", f"_OBJC_METACLASS_$_{x}"))
    return out


def open_image(path):
    """MachO for a binary, or Merged for a JSON spec
    {"main": path, "libs": [[path, slide] or [path, slide, {"native_tbd": tbd}], ...]}."""
    if path.endswith(".json"):
        import json
        import subprocess
        spec = json.load(open(path))
        libs = []
        for e in spec.get("libs", []):
            p, sl = e[0], int(e[1], 0) if isinstance(e[1], str) else e[1]
            nat, rp = set(), e[2].get("replaces", []) if len(e) > 2 else []
            if len(e) > 2 and e[2].get("native_tbd"):
                t = e[2]["native_tbd"]
                if not t.startswith("/"):
                    t = subprocess.check_output(["xcrun", "--show-sdk-path"], text=True).strip() + "/" + t
                nat = tbd_symbols(t)
            libs.append((p, sl, nat, rp))
        return Merged(spec["main"], libs)
    return MachO(path)
