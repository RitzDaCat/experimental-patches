#!/usr/bin/env bash

set -euo pipefail

destination=${1:?destination directory required}
duration_seconds=10
auxiliary_duration_seconds=10

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
"$root/scripts/check_trace_safety.sh"
mkdir -p "$destination"

clock_file="$destination/clock-correlation.tsv"
python3 "$root/tools/capture_clock_sync.py" pre-window --header > "$clock_file"

find_nvidia_card() {
    local card vendor
    for card in /sys/class/drm/card[0-9]*; do
        [[ -r $card/device/vendor ]] || continue
        read -r vendor < "$card/device/vendor"
        if [[ $vendor == 0x10de ]]; then
            printf '/dev/dri/%s\n' "${card##*/}"
            return 0
        fi
    done
    return 1
}

probe_source="$root/tools/drm_color_pipeline_probe.cpp"
probe_binary="$root/artifacts/build/tools/drm_color_pipeline_probe"
drm_card=$(find_nvidia_card || true)
if [[ -n $drm_card && -r $drm_card && -w $drm_card ]] && command -v g++ >/dev/null && command -v pkg-config >/dev/null; then
    if [[ ! -x $probe_binary || $probe_source -nt $probe_binary ]]; then
        mkdir -p "$(dirname "$probe_binary")"
        # shellcheck disable=SC2046
        g++ -std=c++20 -O2 -Wall -Wextra -Wpedantic \
            $(pkg-config --cflags libdrm) "$probe_source" \
            -o "$probe_binary" $(pkg-config --libs libdrm)
    fi
    "$probe_binary" --device "$drm_card" --blob-dir "$destination/drm-blobs-before" \
        > "$destination/drm-color-before.txt" 2>&1 || true
    find "$destination/drm-blobs-before" -type f -print0 2>/dev/null \
        | sort -z | xargs -0 -r sha256sum > "$destination/drm-blobs-before.sha256"
else
    printf 'DRM color probe unavailable (card=%s readable=%s writable=%s)\n' \
        "${drm_card:-not-found}" \
        "$([[ -n $drm_card && -r $drm_card ]] && printf yes || printf no)" \
        "$([[ -n $drm_card && -w $drm_card ]] && printf yes || printf no)" \
        > "$destination/drm-color-before.txt"
fi

critical_processes=(kwin_wayland pipewire pipewire-pulse wireplumber goxlr-daemon)
declare -a keys labels pids tids before_runtime before_wait before_switches

for process_name in "${critical_processes[@]}"; do
    while read -r pid; do
        [[ -n $pid ]] || continue
        for task in /proc/"$pid"/task/*; do
            [[ -r $task/comm && -r $task/schedstat ]] || continue
            read -r thread_name < "$task/comm"
            tid=${task##*/}
            keys+=("$pid:$tid")
            labels+=("$process_name/$thread_name")
            pids+=("$pid")
            tids+=("$tid")
            read -r runtime wait switches < "$task/schedstat"
            before_runtime+=("$runtime")
            before_wait+=("$wait")
            before_switches+=("$switches")
        done
    done < <(pgrep -x "$process_name" 2>/dev/null || true)
done

boot_id=$(< /proc/sys/kernel/random/boot_id)
kwin_pid=$(pgrep -n -x kwin_wayland 2>/dev/null || true)
kwin_start_epoch=
if [[ -n $kwin_pid && -d /proc/$kwin_pid ]]; then
    kwin_start_epoch=$(stat -c %Y "/proc/$kwin_pid")
fi
ps -eLo pid,tid,cls,rtprio,pri,psr,pcpu,stat,time,comm,args --sort=-pcpu \
    > "$destination/processes-before.txt"
cat /proc/interrupts > "$destination/interrupts-before.txt"

python3 "$root/tools/capture_clock_sync.py" window-start >> "$clock_file"
start_epoch=$(date +%s)
start_epoch_ns=$(date +%s%N)
start_monotonic_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
start_monotonic_raw_ns=$(python3 -c 'import time; print(time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW))')
# CLOCK_BOOTTIME includes suspend; CLOCK_MONOTONIC does not. Deriving the boot
# epoch from the monotonic clock places it late by the total suspended time, so
# after a resume the analyzer rejects live telemetry as "from an earlier boot".
start_boottime_ns=$(python3 -c 'import time; print(time.clock_gettime_ns(time.CLOCK_BOOTTIME))')
{
    printf 'duration_seconds=%s\n' "$duration_seconds"
    printf 'start_epoch=%s\n' "$start_epoch"
    printf 'start_epoch_ns=%s\n' "$start_epoch_ns"
    printf 'kernel=%s\n' "$(uname -r)"
    printf 'start_monotonic_ns=%s\n' "$start_monotonic_ns"
    printf 'start_monotonic_raw_ns=%s\n' "$start_monotonic_raw_ns"
    printf 'start_boottime_ns=%s\n' "$start_boottime_ns"
    printf 'boot_id=%s\n' "$boot_id"
    printf 'kwin_pid=%s\n' "$kwin_pid"
    printf 'kwin_start_epoch=%s\n' "$kwin_start_epoch"
} > "$destination/window.txt"

sleep "$duration_seconds"

end_epoch=$(date +%s)
end_epoch_ns=$(date +%s%N)
end_monotonic_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
end_monotonic_raw_ns=$(python3 -c 'import time; print(time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW))')
printf 'end_epoch=%s\n' "$end_epoch" >> "$destination/window.txt"
printf 'end_epoch_ns=%s\n' "$end_epoch_ns" >> "$destination/window.txt"
printf 'end_monotonic_ns=%s\n' "$end_monotonic_ns" >> "$destination/window.txt"
printf 'end_monotonic_raw_ns=%s\n' "$end_monotonic_raw_ns" >> "$destination/window.txt"
python3 "$root/tools/capture_clock_sync.py" post-window >> "$clock_file"
printf 'label\tpid\ttid\tcpu_ms\trunqueue_wait_ms\tswitches\n' \
    > "$destination/thread-deltas.tsv"
for index in "${!keys[@]}"; do
    task=/proc/"${pids[$index]}"/task/"${tids[$index]}"
    [[ -r $task/schedstat ]] || continue
    read -r runtime wait switches < "$task/schedstat"
    awk \
        -v label="${labels[$index]}" \
        -v pid="${pids[$index]}" \
        -v tid="${tids[$index]}" \
        -v before_runtime="${before_runtime[$index]}" \
        -v before_wait="${before_wait[$index]}" \
        -v before_switches="${before_switches[$index]}" \
        -v runtime="$runtime" \
        -v wait="$wait" \
        -v switches="$switches" \
        'BEGIN { printf "%s\t%s\t%s\t%.6f\t%.6f\t%d\n", label, pid, tid, (runtime - before_runtime) / 1000000, (wait - before_wait) / 1000000, switches - before_switches }' \
        >> "$destination/thread-deltas.tsv"
done

ps -eLo pid,tid,cls,rtprio,pri,psr,pcpu,stat,time,comm,args --sort=-pcpu \
    > "$destination/processes-after.txt"
cat /proc/interrupts > "$destination/interrupts-after.txt"

if [[ -n $drm_card && -x $probe_binary ]]; then
    "$probe_binary" --device "$drm_card" --blob-dir "$destination/drm-blobs-after" \
        > "$destination/drm-color-after.txt" 2>&1 || true
    find "$destination/drm-blobs-after" -type f -print0 2>/dev/null \
        | sort -z | xargs -0 -r sha256sum > "$destination/drm-blobs-after.sha256"
fi

# GPU and audio samplers run after the precision window. Their driver queries
# and text formatting are valuable state evidence, but must not perturb the
# frame-timing distribution being measured above.
declare -a background_pids=()
auxiliary_start_monotonic_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
printf 'auxiliary_start_monotonic_ns=%s\n' "$auxiliary_start_monotonic_ns" >> "$destination/window.txt"
if command -v nvidia-smi >/dev/null; then
    timeout "$auxiliary_duration_seconds" nvidia-smi \
        --query-gpu=timestamp,pstate,utilization.gpu,utilization.memory,clocks.current.graphics,clocks.current.memory,power.draw,temperature.gpu \
        --format=csv -l 1 > "$destination/nvidia-window.csv" 2>&1 &
    background_pids+=("$!")
fi
if command -v pw-top >/dev/null; then
    timeout "$auxiliary_duration_seconds" pw-top -b > "$destination/pipewire-window.txt" 2>&1 &
    background_pids+=("$!")
fi
for background_pid in "${background_pids[@]}"; do
    wait "$background_pid" 2>/dev/null || true
done
auxiliary_end_monotonic_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
printf 'auxiliary_end_monotonic_ns=%s\n' "$auxiliary_end_monotonic_ns" >> "$destination/window.txt"

command -v pw-top >/dev/null && timeout 3 pw-top -b -n 2 \
    > "$destination/pipewire-after.txt" 2>&1 || true
journalctl --user --since "@$start_epoch" --until "@$end_epoch" --no-pager -o short-precise 2>/dev/null \
    | grep -Ei 'overrun|underrun|xrun|out of buffers|pipewire.*error|goxlr.*recover' \
    > "$destination/audio-faults.txt" || true

telemetry_destination="$destination/kwin-telemetry"
mkdir -p "$telemetry_destination"
printf 'source\tbytes\tmodified_epoch\n' > "$destination/telemetry-files.tsv"
shopt -s nullglob
telemetry_files=(
    "$HOME"/kwin\ perf\ statistics\ *.csv
    "$HOME"/kwin\ input\ latency.csv
    "$HOME"/kwin\ drm\ timing\ *.csv
    "$HOME"/kwin\ color\ pipeline.log
    "$HOME"/kwin\ drm\ color\ match.log
)
for telemetry_file in "${telemetry_files[@]}"; do
    [[ -f $telemetry_file ]] || continue
    printf '%s\t%s\t%s\n' \
        "$telemetry_file" \
        "$(stat -c %s "$telemetry_file")" \
        "$(stat -c %Y "$telemetry_file")" \
        >> "$destination/telemetry-files.tsv"
    cp -a "$telemetry_file" "$telemetry_destination/"
done
shopt -u nullglob

printf 'Pipeline window saved: %s\n' "$destination"
