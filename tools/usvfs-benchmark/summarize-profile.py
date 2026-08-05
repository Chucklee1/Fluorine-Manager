#!/usr/bin/env python3
"""Summarize opt-in USVFS profiler records without third-party modules."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


PROFILE = re.compile(r"\[profile\]\s+(.*)$")
PAIR = re.compile(r"([a-z_0-9]+)=([^\s]+)")
SOURCE = re.compile(
    r"source=(.*?)\s+acquisitions=(\d+)\s+contended=(\d+)\s+"
    r"wait_ticks=(\d+)\s+max_wait_ticks=(\d+)"
)


def records(path: pathlib.Path) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = PROFILE.search(line)
        if not match:
            continue
        body = match.group(1)
        values = dict(PAIR.findall(body))
        if values.get("kind") == "context_lock_source":
            source = SOURCE.search(body)
            if source:
                values.update(
                    source=source.group(1),
                    acquisitions=source.group(2),
                    contended=source.group(3),
                    wait_ticks=source.group(4),
                    max_wait_ticks=source.group(5),
                )
        values["input"] = str(path)
        parsed.append(values)
    return parsed


def integer(record: dict[str, str], name: str) -> int:
    return int(record.get(name, "0"))


def milliseconds(ticks: int, frequency: int) -> float:
    return ticks * 1000.0 / frequency if frequency else 0.0


def latest(
    rows: list[dict[str, str]], extra_key: tuple[str, ...] = ()
) -> list[dict[str, str]]:
    selected: dict[tuple[str, ...], dict[str, str]] = {}
    for row in rows:
        key = (row["input"], row.get("pid", "0")) + tuple(
            row.get(field, "") for field in extra_key
        )
        previous = selected.get(key)
        if previous is None or integer(row, "snapshot") >= integer(
            previous, "snapshot"
        ):
            selected[key] = row
    return list(selected.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", nargs="+", type=pathlib.Path)
    arguments = parser.parse_args()
    all_records = [record for path in arguments.profiles for record in records(path)]
    locks = latest([r for r in all_records if r.get("kind") == "context_lock"])
    directories = latest(
        [r for r in all_records if r.get("kind") == "directory_query"]
    )
    information_classes = latest(
        [r for r in all_records if r.get("kind") == "directory_information_class"],
        ("class",),
    )
    directory_work = latest(
        [r for r in all_records if r.get("kind") == "directory_work"]
    )
    sources = latest(
        [r for r in all_records if r.get("kind") == "context_lock_source"],
        ("source",),
    )
    cache_observers = latest(
        [
            r
            for r in all_records
            if r.get("kind")
            in {"tree_lookup_cache", "negative_attribute_cache"}
        ],
        ("kind",),
    )
    if not locks and not directories:
        print("No USVFS profiler summaries found.", file=sys.stderr)
        return 1

    print("LOCKS")
    print(
        "input\tpid\tacquisitions\tcontended\tcontention_pct\treads\twrites\t"
        "recursive\twait_ms\tmax_wait_ms\thold_ms\tmax_hold_ms\tmax_depth"
    )
    frequencies: dict[tuple[str, str], int] = {}
    for record in locks:
        frequency = integer(record, "qpc_frequency")
        key = (record["input"], record.get("pid", "0"))
        frequencies[key] = frequency
        acquisitions = integer(record, "acquisitions")
        contended = integer(record, "contended")
        print(
            record["input"],
            record.get("pid", "0"),
            acquisitions,
            contended,
            f"{(contended * 100.0 / acquisitions if acquisitions else 0.0):.4f}",
            integer(record, "reads"),
            integer(record, "writes"),
            integer(record, "recursive"),
            f'{milliseconds(integer(record, "wait_ticks"), frequency):.3f}',
            f'{milliseconds(integer(record, "max_wait_ticks"), frequency):.3f}',
            f'{milliseconds(integer(record, "hold_ticks"), frequency):.3f}',
            f'{milliseconds(integer(record, "max_hold_ticks"), frequency):.3f}',
            integer(record, "max_depth"),
            sep="\t",
        )

    print("\nDIRECTORY_QUERIES")
    fields = [
        "input",
        "pid",
        "total",
        "legacy",
        "ex",
        "single",
        "restart",
        "pattern_null",
        "pattern_exact",
        "pattern_wildcard",
        "first_search",
        "virtual_remaining",
        "success",
        "no_more",
        "no_such",
        "other_status",
        "buffer_le_64",
        "buffer_le_256",
        "buffer_le_1024",
        "buffer_le_4096",
        "buffer_le_16384",
        "buffer_gt_16384",
    ]
    print("\t".join(fields))
    for record in directories:
        print("\t".join(record.get(field, "0") for field in fields))

    print("\nDIRECTORY_INFORMATION_CLASSES")
    print("input\tpid\tclass\tcount")
    for record in sorted(
        information_classes,
        reverse=True,
        key=lambda row: integer(row, "count"),
    ):
        print(
            record["input"],
            record.get("pid", "0"),
            integer(record, "class"),
            integer(record, "count"),
            sep="\t",
        )

    print("\nDIRECTORY_WORK")
    print(
        "input\tpid\tparent_opens\tparent_open_failures\tparent_open_ms\t"
        "parent_open_max_ms\tregular_queries\tregular_query_ms\t"
        "regular_query_max_ms\tvirtual_queries\tvirtual_query_ms\t"
        "virtual_query_max_ms\tbacking_success\tbacking_no_more\t"
        "backing_other_status"
    )
    for record in directory_work:
        frequency = integer(record, "qpc_frequency")
        print(
            record["input"],
            record.get("pid", "0"),
            integer(record, "parent_opens"),
            integer(record, "parent_open_failures"),
            f'{milliseconds(integer(record, "parent_open_ticks"), frequency):.3f}',
            f'{milliseconds(integer(record, "parent_open_max_ticks"), frequency):.3f}',
            integer(record, "regular_queries"),
            f'{milliseconds(integer(record, "regular_query_ticks"), frequency):.3f}',
            f'{milliseconds(integer(record, "regular_query_max_ticks"), frequency):.3f}',
            integer(record, "virtual_queries"),
            f'{milliseconds(integer(record, "virtual_query_ticks"), frequency):.3f}',
            f'{milliseconds(integer(record, "virtual_query_max_ticks"), frequency):.3f}',
            integer(record, "backing_success"),
            integer(record, "backing_no_more"),
            integer(record, "backing_other_status"),
            sep="\t",
        )

    print("\nCACHE_OBSERVERS")
    print(
        "input\tpid\tkind\tslots\ttotal\tpositive\tnegative\t"
        "repeat_positive\trepeat_negative\tchanged\tfirst_use\treplacements"
    )
    for record in cache_observers:
        print(
            record["input"],
            record.get("pid", "0"),
            record.get("kind", ""),
            integer(record, "slots"),
            integer(record, "total"),
            integer(record, "positive"),
            integer(record, "negative"),
            integer(record, "repeat_positive"),
            integer(record, "repeat_negative"),
            integer(record, "changed"),
            integer(record, "first_use"),
            integer(record, "replacements"),
            sep="\t",
        )

    print("\nLOCK_SOURCES_BY_WAIT")
    print("input\tpid\tsource\tacquisitions\tcontended\twait_ms\tmax_wait_ms")
    ranked: list[tuple[float, dict[str, str], int]] = []
    for record in sources:
        key = (record["input"], record.get("pid", "0"))
        frequency = frequencies.get(key, 0)
        wait_ms = milliseconds(integer(record, "wait_ticks"), frequency)
        ranked.append((wait_ms, record, frequency))
    for wait_ms, record, frequency in sorted(ranked, reverse=True, key=lambda row: row[0]):
        print(
            record["input"],
            record.get("pid", "0"),
            record.get("source", "<unknown>"),
            integer(record, "acquisitions"),
            integer(record, "contended"),
            f"{wait_ms:.3f}",
            f'{milliseconds(integer(record, "max_wait_ticks"), frequency):.3f}',
            sep="\t",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
