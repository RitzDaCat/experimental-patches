#!/usr/bin/env bash
# Modified 2026-10-08: keep standalone benchmark output in its ignored folder.

set -euo pipefail

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$project_root/artifacts/observer-bench"
"${CXX:-c++}" -O3 -std=c++20 -DNDEBUG \
    "$project_root/bench/observer_cost.cpp" \
    -o "$project_root/artifacts/observer-bench/observer_cost_bench"
exec "$project_root/artifacts/observer-bench/observer_cost_bench" "${1:-10000000}" "${2:-64}"
