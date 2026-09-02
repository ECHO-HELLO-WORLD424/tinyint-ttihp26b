#!/usr/bin/env python3
"""Check mapped accumulator-state toggles in four post-layout VCD traces."""

import pathlib
import sys


GROUPS = {
    "conventional": "core.conventional_accumulator.accumulator_value[",
    "dynamic_low8": "core.dynamic_accumulator.accumulator_value[",
}


def parse_state_toggles(path):
    codes = {}
    values = {}
    toggles = {"conventional": 0, "d0_7": 0, "d8_11": 0,
               "d12_15": 0, "d16_19": 0}
    declarations = True

    with pathlib.Path(path).open(encoding="ascii", errors="strict") as stream:
        for line in stream:
            line = line.strip()
            if declarations:
                if line.startswith("$var "):
                    fields = line.split()
                    code = fields[3]
                    name = " ".join(fields[4:-1]).lstrip("\\")
                    if GROUPS["conventional"] in name:
                        codes[code] = "conventional"
                    elif GROUPS["dynamic_low8"] in name:
                        bit = int(name.rsplit("[", 1)[1].split("]", 1)[0])
                        if bit < 8:
                            codes[code] = "d0_7"
                        elif bit < 12:
                            codes[code] = "d8_11"
                        elif bit < 16:
                            codes[code] = "d12_15"
                        else:
                            codes[code] = "d16_19"
                elif line == "$enddefinitions $end":
                    declarations = False
                continue

            if not line or line[0] in "$#br":
                continue
            value = line[0]
            code = line[1:]
            if code not in codes or value not in "01":
                continue
            if code in values and values[code] != value:
                toggles[codes[code]] += 1
            values[code] = value

    if len(codes) != 40:
        raise AssertionError(f"{path}: expected 40 accumulator state bits, found {len(codes)}")
    return toggles


def main(paths):
    if len(paths) != 4:
        raise SystemExit("usage: analyze_activity.py conventional.vcd dynamic8.vcd dynamic12.vcd dynamic16.vcd")
    reports = [parse_state_toggles(path) for path in paths]

    assert reports[0]["conventional"] > 0
    assert sum(reports[0][key] for key in reports[0] if key != "conventional") == 0
    for report in reports[1:]:
        assert report["conventional"] == 0

    boundaries = (8, 12, 16)
    groups = (("d0_7",), ("d0_7", "d8_11"),
              ("d0_7", "d8_11", "d12_15"))
    cold_groups = (("d8_11", "d12_15", "d16_19"),
                   ("d12_15", "d16_19"), ("d16_19",))
    for report, boundary, active, cold in zip(reports[1:], boundaries, groups, cold_groups):
        active_toggles = sum(report[key] for key in active)
        cold_toggles = sum(report[key] for key in cold)
        active_bits = boundary
        cold_bits = 20 - boundary
        assert active_toggles > 0
        assert cold_toggles * active_bits < active_toggles * cold_bits, (
            f"boundary {boundary}: cold state did not toggle less per bit")

    names = ("conventional", "dynamic8", "dynamic12", "dynamic16")
    print("mode,conventional,dynamic[7:0],dynamic[11:8],dynamic[15:12],dynamic[19:16]")
    for name, report in zip(names, reports):
        print(f"{name},{report['conventional']},{report['d0_7']},{report['d8_11']},"
              f"{report['d12_15']},{report['d16_19']}")
    print("PASS: unselected state is static and every dynamic cold region toggles less per bit")


if __name__ == "__main__":
    main(sys.argv[1:])
