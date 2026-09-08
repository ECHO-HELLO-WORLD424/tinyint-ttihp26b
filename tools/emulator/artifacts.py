# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""Locate and prepare the physical artifacts needed for PVT simulation.

The RTL backend needs nothing from this module.  The SDF (PVT) backend needs
three things that must belong to the *same* hardened build:

  1. a post-route gate-level netlist,
  2. a per-corner SDF (delay annotation),
  3. the timing-safe standard-cell library used by ``tools/sdf/make_sdf_lib.py``.

Raw SDF and raw netlists cannot be fed to Icarus directly:

  * the netlist keeps Yosys escaped instance names (``\\u_dut.g_seg[0]...``)
    and Icarus' SDF binder treats dots as hierarchy separators, so both the
    netlist copy and the SDF ``(INSTANCE ...)`` fields are rewritten to
    underscore form (``tools/sdf/rename_netlist.py``, ``tools/sdf/filter_sdf.py``);
  * the corner SDF carries an INTERCONNECT block that crashes Icarus' annotator
    and TIMINGCHECK blocks whose checks the patched library cannot execute, so
    the SDF is reduced to per-cell IOPATH delays.

Prepared files are cached under ``runs/emulator/sdf/`` (git-ignored) together
with a stamp that records source paths, hashes and the build identity.

This module is cocotb-free.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .pvt import PVT, REPO, get_corner

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO, "runs", "emulator", "sdf")
_RUN_RE = re.compile(r"run-(\d+)")


# ------------------------------------------------------------------ helpers --


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: str) -> str:
    try:
        return os.path.relpath(path, REPO)
    except ValueError:
        return path


def _glob(pattern: str) -> List[str]:
    return sorted(p for p in glob.glob(os.path.join(REPO, pattern)) if os.path.isfile(p))


def run_id(path: str) -> Optional[str]:
    """Hardening run identity encoded in an artifact path, if any."""
    m = _RUN_RE.search(path)
    return m.group(1) if m else None


@dataclass
class Artifact:
    path: str
    kind: str            # netlist | sdf | lib
    filtered: bool = False
    run: Optional[str] = None

    def __post_init__(self) -> None:
        if self.run is None:
            self.run = run_id(self.path)

    def __str__(self) -> str:
        return _rel(self.path)


@dataclass
class CornerArtifacts:
    """Everything the SDF backend needs for one corner, ready for Icarus."""

    corner: PVT
    netlist: str
    sdf: str
    stdcell_lib: str
    netlist_source: str
    sdf_source: str
    filter_log: str = ""
    provenance: Dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        return (
            "netlist %s (sha256 %s)\n"
            "  sdf     %s (sha256 %s)\n"
            "  lib     %s\n"
            "  origin  netlist <- %s\n"
            "          sdf     <- %s%s"
            % (
                _rel(self.netlist), _sha256(self.netlist)[:12],
                _rel(self.sdf), _sha256(self.sdf)[:12],
                _rel(self.stdcell_lib),
                _rel(self.netlist_source), _rel(self.sdf_source),
                ("\n          " + self.filter_log.strip()) if self.filter_log else "",
            )
        )


# ------------------------------------------------------------------ search ---

_NETLIST_PATTERNS = [
    "test/gate_level_netlist.v",
    "src/runs/*/final/nl/*.nl.v",
    "runs/*/final/nl/*.nl.v",
    "runs/*/nl/*.nl.v",
    "artifacts/run-*/nl/*.nl.v",
    "artifacts/run-*/**/nl/*.nl.v",
    "data/*/sdfsim/netlist_sim.v",
]

_LIB_PATTERNS = [
    "runs/emulator/sdf/sg13g2_stdcell_sdf.v",
    "data/sdfsim/sg13g2_stdcell_sdf.v",
    "data/*/sdfsim/sg13g2_stdcell_sdf.v",
]


def find_netlists() -> List[Artifact]:
    """Candidate post-route netlists, best (raw, newest) first."""
    seen, out = set(), []
    for pat in _NETLIST_PATTERNS:
        for path in _glob(pat):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            # an already-renamed copy is a cache, not a source
            filtered = os.path.basename(path) == "netlist_sim.v"
            out.append(Artifact(path, "netlist", filtered=filtered))
    # raw netlists first, newest first
    out.sort(key=lambda a: (a.filtered, -os.path.getmtime(a.path)))
    return out


def find_sdfs(corner: PVT) -> List[Artifact]:
    """Candidate SDFs for a corner: filtered copies first, then raw."""
    name = corner.name
    patterns = [
        "data/*/sdf_path/%s.iopath.sdf" % name,
        "runs/emulator/sdf/%s.iopath.sdf" % name,
        "artifacts/run-*/sdf/%s/*.sdf" % name,
        "artifacts/run-*/54-openroad-stapostpnr/%s/*.sdf" % name,
        "src/runs/*/sdf/%s/*.sdf" % name,
        "runs/*/sdf/%s/*.sdf" % name,
    ]
    seen, out = set(), []
    for pat in patterns:
        for path in _glob(pat):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            out.append(Artifact(path, "sdf", filtered=path.endswith(".iopath.sdf")))
    return out


def find_stdcell_lib() -> Optional[Artifact]:
    for pat in _LIB_PATTERNS:
        for path in _glob(pat):
            return Artifact(path, "lib", filtered=True)
    return None


def generate_stdcell_lib(dest: Optional[str] = None) -> Optional[Artifact]:
    """Build the timing-safe library from the PDK (needs the devcontainer)."""
    import shutil

    maker = os.path.join(TOOLS, "sdf", "make_sdf_lib.py")
    env_pdk = os.environ.get("PDK_ROOT") or os.environ.get("PDK")
    if not (env_pdk or os.path.isdir("/home/vscode/ttsetup/pdk")):
        return None
    before = set(_glob("data/*/sdfsim/sg13g2_stdcell_sdf.v"))
    res = subprocess.run([sys.executable, maker], capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stdout + res.stderr)
        return None
    produced = [p for p in _glob("data/*/sdfsim/sg13g2_stdcell_sdf.v")
                if p not in before] or _glob("data/*/sdfsim/sg13g2_stdcell_sdf.v")
    if not produced:
        return None
    src = max(produced, key=os.path.getmtime)
    dest = dest or os.path.join(CACHE_DIR, "sg13g2_stdcell_sdf.v")
    if os.path.abspath(dest) != os.path.abspath(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
    return Artifact(dest, "lib", filtered=True)


def availability() -> Dict[str, dict]:
    """Per-corner artifact report for the ``corners`` command."""
    report = {}
    for name, corner in ((c.name, c) for c in _all_corners()):
        sdfs = find_sdfs(corner)
        report[name] = {
            "pvt": corner,
            "netlists": len(find_netlists()),
            "sdfs": [(str(s), s.filtered, s.run) for s in sdfs],
            "lib": str(find_stdcell_lib() or ""),
        }
    return report


def _all_corners() -> List[PVT]:
    from .pvt import CORNERS
    return list(CORNERS.values())


# ------------------------------------------------------------------ prepare --


def _pick_pair(netlists: List[Artifact], sdfs: List[Artifact]):
    """Pair the netlist and SDF that most likely come from the same build."""
    best, best_score = None, None
    for n in netlists:
        for s in sdfs:
            score = 0
            if n.run and s.run and n.run == s.run:
                score += 100
            if s.filtered:
                score += 10
            if not n.filtered:
                score += 5
            # prefer newest sources when everything else ties
            score += min(os.path.getmtime(s.path) / 1e12, 0.9)
            if best_score is None or score > best_score:
                best, best_score = (n, s), score
    return best


def prepare(corner: "PVT | str | None" = None, cache_dir: str = CACHE_DIR,
            force: bool = False, sdf: Optional[str] = None,
            netlist: Optional[str] = None) -> CornerArtifacts:
    """Return Icarus-ready (netlist, SDF, library) paths for a corner.

    ``sdf`` / ``netlist`` override artifact discovery, e.g. for a custom
    corner SDF produced by a different LibreLane run.
    """
    if isinstance(corner, str) or corner is None:
        corner = get_corner(corner)

    lib = find_stdcell_lib() or generate_stdcell_lib()
    if lib is None:
        raise SystemExit(
            "no timing-safe standard-cell library found.\n"
            "Expected data/sdfsim/sg13g2_stdcell_sdf.v or a PDK to build it:\n"
            "  python3 tools/sdf/make_sdf_lib.py   (inside the devcontainer)"
        )

    sdfs: List[Artifact] = []
    netlists: List[Artifact] = []

    if sdf:
        sdf_art = Artifact(os.path.abspath(sdf), "sdf",
                           filtered=os.path.abspath(sdf).endswith(".iopath.sdf"))
        if not os.path.isfile(sdf_art.path):
            raise SystemExit("SDF not found: %s" % sdf)
    else:
        sdfs = find_sdfs(corner)
        if not sdfs:
            raise SystemExit(
                "no SDF for corner %s.\n"
                "Looked for data/*/sdf_path/%s.iopath.sdf and "
                "artifacts/run-*/sdf/%s/*.sdf.\n"
                "Add a corner SDF or run: python3 tools/chip_emulate.py prepare"
                % (corner, corner.name, corner.name)
            )
        sdf_art = None

    if netlist:
        nl_art = Artifact(os.path.abspath(netlist), "netlist")
        if not os.path.isfile(nl_art.path):
            raise SystemExit("netlist not found: %s" % netlist)
    else:
        netlists = find_netlists()
        if not netlists:
            raise SystemExit(
                "no post-route netlist found.\n"
                "Looked under artifacts/run-*/nl/, src/runs/*/final/nl/, "
                "runs/ and test/gate_level_netlist.v."
            )
        nl_art = None

    if sdf_art is None or nl_art is None:
        picked = _pick_pair(netlists, sdfs)
        if picked is None:
            raise SystemExit("could not pair a netlist with an SDF")
        nl_art = nl_art or picked[0]
        sdf_art = sdf_art or picked[1]

    os.makedirs(cache_dir, exist_ok=True)
    tag = nl_art.run or "local"
    nl_dst = os.path.join(cache_dir, "netlist_%s.v" % tag)
    sdf_dst = os.path.join(cache_dir, "%s.iopath.sdf" % corner.name)
    stamp_path = os.path.join(cache_dir, "%s.stamp.json" % corner.name)

    stamp = {}
    if os.path.isfile(stamp_path) and not force:
        try:
            stamp = json.load(open(stamp_path))
        except (OSError, ValueError):
            stamp = {}

    want = {
        "netlist_source": nl_art.path,
        "netlist_sha256": _sha256(nl_art.path),
        "sdf_source": sdf_art.path,
        "sdf_sha256": _sha256(sdf_art.path),
        "lib": lib.path,
    }
    if (stamp.get("want") == want
            and os.path.isfile(nl_dst) and os.path.isfile(sdf_dst)):
        return CornerArtifacts(
            corner=corner, netlist=nl_dst, sdf=sdf_dst, stdcell_lib=lib.path,
            netlist_source=nl_art.path, sdf_source=sdf_art.path,
            filter_log=stamp.get("filter_log", ""),
            provenance=stamp.get("provenance", {}),
        )

    # --- (re)build the cache -------------------------------------------------
    rename = os.path.join(TOOLS, "sdf", "rename_netlist.py")
    res = subprocess.run([sys.executable, rename, nl_art.path, nl_dst],
                         capture_output=True, text=True)
    if res.returncode != 0:
        sys.stderr.write(res.stdout + res.stderr)
        raise SystemExit("netlist rename failed for %s" % nl_art.path)

    filter_log = ""
    if sdf_art.filtered:
        # already reduced to IOPATH-only form: copy so the cache is self-contained
        with open(sdf_art.path, "rb") as src, open(sdf_dst, "wb") as dst:
            dst.write(src.read())
        filter_log = "reused filtered SDF %s" % _rel(sdf_art.path)
    else:
        filt = os.path.join(TOOLS, "sdf", "filter_sdf.py")
        res = subprocess.run([sys.executable, filt, sdf_art.path, sdf_dst],
                             capture_output=True, text=True)
        if res.returncode != 0:
            sys.stderr.write(res.stdout + res.stderr)
            raise SystemExit("SDF filtering failed for %s" % sdf_art.path)
        filter_log = res.stdout.strip()

    provenance = {
        "netlist_source": _rel(nl_art.path),
        "netlist_sha256": want["netlist_sha256"][:16],
        "sdf_source": _rel(sdf_art.path),
        "sdf_sha256": want["sdf_sha256"][:16],
        "run": tag,
        "filter": filter_log,
    }
    with open(stamp_path, "w") as fh:
        json.dump({"want": want, "filter_log": filter_log,
                   "provenance": provenance}, fh, indent=1)

    return CornerArtifacts(
        corner=corner, netlist=nl_dst, sdf=sdf_dst, stdcell_lib=lib.path,
        netlist_source=nl_art.path, sdf_source=sdf_art.path,
        filter_log=filter_log, provenance=provenance,
    )


def main(argv: Optional[List[str]] = None) -> int:
    """``prepare`` CLI: build the SDF cache for every available corner."""
    from .pvt import corner_names
    argv = list(sys.argv[1:] if argv is None else argv)
    names = argv or corner_names()
    rc = 0
    for name in names:
        corner = get_corner(name)
        try:
            art = prepare(corner)
        except SystemExit as exc:
            print("skip %-24s %s" % (name, exc))
            rc = 1
            continue
        print("ok   %-24s %s" % (name, _rel(art.sdf)))
        print("     %s" % _rel(art.netlist))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
