#!/usr/bin/env python3
"""Standalone CPU/memory benchmark probe for cluster node comparison.

Deliberately NOT the production Discogs parser (packages/catalog) -- a
minimal, dependency-free (stdlib only) probe that models the same
bottleneck this project already profiled for real: repeated per-child XML
text lookups (see docs/DATA_SIZING.md's "Real profiling" section, and
_child_text_map's docstring in
packages/catalog/src/networked_players_catalog/discogs/releases.py for the
production fix). This probe intentionally keeps the pre-fix O(n)
child-rescan shape via findtext() -- it's a CPU stress probe for comparing
node types, not a correctness benchmark, and must run unmodified on
hardware (a Raspberry Pi 3B, a second ZimaBoard 832) that isn't wired up
yet to test dependency installation against. Zero pip/apt dependencies.

Usage: python3 benchmark_parse.py [iterations]
   or: BENCHMARK_ITERATIONS=20000 python3 benchmark_parse.py
Prints one JSON line to stdout.
"""

from __future__ import annotations

import json
import os
import platform
import resource
import socket
import sys
import time
import xml.etree.ElementTree as ET

# The project's own synthetic parsing fixture
# (packages/catalog/tests/fixtures/releases.xml), embedded so this probe
# has zero external dependencies -- no network fetch, no repo checkout
# needed on the target node.
FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<releases>
  <release id="101" status="Accepted">
    <artists>
      <artist><id>11</id><name>Alpha Group</name><anv>Alpha</anv><join>&amp;</join></artist>
      <artist><id>12</id><name>Beta Singer</name><join></join></artist>
    </artists>
    <title>Connected Record</title>
    <country>US</country>
    <released>2001</released>
    <master_id is_main_release="true">501</master_id>
    <extraartists>
      <artist><id>21</id><name>Pat Producer</name><role>Producer, Engineer</role></artist>
      <artist><id>0</id><name>Unlinked Orchestra</name><role>Strings</role>
        <tracks>A2</tracks></artist>
    </extraartists>
    <tracklist>
      <track>
        <position>A1</position><title>First Track</title><duration>3:15</duration>
        <artists><artist><id>11</id><name>Alpha Group</name></artist></artists>
        <extraartists><artist><id>31</id><name>Casey Guitar</name><anv>C. Guitar</anv>
          <role>Guitar</role></artist></extraartists>
      </track>
      <track>
        <position>A2</position><title>Second Track</title><duration>4:02</duration>
        <extraartists><artist><name>Anonymous Choir</name>
          <role>Vocals</role></artist></extraartists>
        <sub_tracks>
          <track>
            <position>A2a</position><title>Nested Part</title><duration>1:02</duration>
            <extraartists><artist><id>32</id><name>Nested Player</name>
              <role>Keyboards</role></artist></extraartists>
          </track>
        </sub_tracks>
      </track>
    </tracklist>
    <data_quality>Correct</data_quality>
  </release>
  <release id="102" status="Accepted">
    <artists><artist><id>40</id><name>Gamma</name></artist></artists>
    <title>Second Record</title>
    <country>GB</country>
    <released>2003-04-01</released>
    <tracklist><track><position>1</position><title>Only Track</title></track></tracklist>
    <data_quality>Needs Vote</data_quality>
  </release>
</releases>
"""

DEFAULT_ITERATIONS = 20000


def _parse_one_release(element: ET.Element) -> dict[str, str | None]:
    return {
        "title": element.findtext("title"),
        "country": element.findtext("country"),
        "released": element.findtext("released"),
        "data_quality": element.findtext("data_quality"),
    }


def run_benchmark(iterations: int) -> dict[str, object]:
    start = time.perf_counter()
    release_count = 0
    for _ in range(iterations):
        root = ET.fromstring(FIXTURE_XML)
        for release in root.findall("release"):
            _parse_one_release(release)
            release_count += 1
    elapsed = time.perf_counter() - start

    # ru_maxrss is KB on Linux (all nodes in this cluster are Linux), a
    # peak-since-process-start value dominated by this loop since it's
    # virtually the whole process runtime.
    peak_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    return {
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "iterations": iterations,
        "releases_parsed": release_count,
        "elapsed_s": round(elapsed, 4),
        "releases_per_sec": (round(release_count / elapsed, 1) if elapsed > 0 else None),
        "peak_rss_mb": round(peak_rss_kb / 1024, 2),
    }


def main() -> None:
    if len(sys.argv) > 1:
        iterations = int(sys.argv[1])
    else:
        iterations = int(os.environ.get("BENCHMARK_ITERATIONS", DEFAULT_ITERATIONS))
    result = run_benchmark(iterations)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
