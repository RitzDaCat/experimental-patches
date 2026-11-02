#!/usr/bin/env bash

set -euo pipefail

if (( $# )); then
    trace_roots=("$@")
else
    trace_roots=(/sys/kernel/tracing /sys/kernel/debug/tracing)
fi

unsafe=0

for trace_root in "${trace_roots[@]}"; do
    event_root="$trace_root/events/dma_fence"
    [[ -d $event_root ]] || continue

    shopt -s nullglob
    # Per-instance tracefs directories carry their own full events/ tree, so a
    # collector can enable dma_fence under instances/<name>/ while the top-level
    # switches all read 0. Scan those too.
    enable_files=(
        "$event_root/enable" "$event_root"/*/enable
        "$trace_root"/instances/*/events/dma_fence/enable
        "$trace_root"/instances/*/events/dma_fence/*/enable
    )
    shopt -u nullglob
    for enable_file in "${enable_files[@]}"; do
        [[ -r $enable_file ]] || continue
        read -r value < "$enable_file" || value=unknown
        if [[ $value != 0 ]]; then
            printf 'error: unsafe dma_fence tracing is active at %s (value=%s)\n' \
                "$enable_file" "$value" >&2
            unsafe=1
        fi
    done
done

while read -r pid command_line; do
    [[ -n $pid && $pid != $$ && $pid != $PPID ]] || continue
    # Project policy forbids the dma_fence tracepoint family via "perf, tracefs,
    # ftrace, BPF, or another collector". Matching only `perf record|trace` let
    # trace-cmd and bpftrace through, so any known tracepoint collector with
    # dma_fence in its argv now counts.
    if [[ $command_line == *dma_fence* ]] \
        && [[ $command_line =~ (^|/)(perf|perf_[^[:space:]]+|trace-cmd|bpftrace|bpftrace-aotrt|funclatency|retsnoop|ftrace|trace|lttng|sysdig|dtrace)([[:space:]]|$) ]]; then
        printf 'error: unsafe dma_fence collector is running as PID %s\n' "$pid" >&2
        unsafe=1
    fi
done < <(ps -eo pid=,args=)

if (( unsafe )); then
    printf 'error: refusing latency capture; stop the fence collector or reboot first\n' >&2
    exit 1
fi

printf 'Kernel trace safety check passed: dma_fence tracing is inactive.\n'
