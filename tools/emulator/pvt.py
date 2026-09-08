# SPDX-FileCopyrightText: (c) 2026 ECHO-HELLO-WORLD424
# SPDX-License-Identifier: Apache-2.0
"""PVT corners for the timing-prediction test vehicle.

A corner is a (name, voltage, temperature) triple.  The names are the IHP
LibreLane corner names already used by the repository's STA / SDF / prediction
tooling (``tools/common.py``), so emulator runs and pre-silicon data sets stay
comparable.

This module is deliberately cocotb-free: it is imported both on the host and
inside the simulator.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import common as _C  # noqa: E402  (repository corner table, single source of truth)

REPO = _C.REPO


@dataclass(frozen=True)
class PVT:
    """A process/voltage/temperature operating point.

    ``name`` must match an IHP LibreLane corner name (or be a user label for a
    custom SDF).  Voltage is the core supply in volts, temperature in Celsius.
    """

    name: str
    voltage_v: float
    temp_c: float

    @property
    def label(self) -> str:
        return "%.2f V, %+.0f C" % (self.voltage_v, self.temp_c)

    def __str__(self) -> str:
        return "%s (%s)" % (self.name, self.label)


CORNERS: Dict[str, PVT] = {
    name: PVT(name, volts, temp) for name, volts, temp in _C.CORNERS
}

# Convenience aliases for interactive use.
ALIASES: Dict[str, str] = {
    "typ": "nom_typ_1p20V_25C",
    "typical": "nom_typ_1p20V_25C",
    "nom": "nom_typ_1p20V_25C",
    "nominal": "nom_typ_1p20V_25C",
    "slow": "nom_slow_1p08V_125C",
    "fast": "nom_fast_1p32V_m40C",
}

DEFAULT_CORNER = "nom_typ_1p20V_25C"


def corner_names() -> List[str]:
    """Corner names in the repository's canonical (fast, typ, slow) order."""
    return list(CORNERS)


def get_corner(name: Optional[str]) -> PVT:
    """Resolve a corner name or alias.  Raises ValueError with the choices."""
    if name is None or name == "":
        return CORNERS[DEFAULT_CORNER]
    key = str(name).strip()
    if key in CORNERS:
        return CORNERS[key]
    low = key.lower()
    if low in ALIASES:
        return CORNERS[ALIASES[low]]
    # unambiguous substring match, e.g. "1p08V" or "125C"
    hits = [c for c in CORNERS if low in c.lower()]
    if len(hits) == 1:
        return CORNERS[hits[0]]
    raise ValueError(
        "unknown PVT corner %r; available: %s" % (name, ", ".join(CORNERS))
    )


def custom_corner(name: str, voltage_v: float, temp_c: float) -> PVT:
    """Label for a user-supplied SDF that has no repository corner name."""
    return PVT(name, float(voltage_v), float(temp_c))
