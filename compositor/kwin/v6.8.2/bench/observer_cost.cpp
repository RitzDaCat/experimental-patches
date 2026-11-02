#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <vector>

using Clock = std::chrono::steady_clock;
using Nanoseconds = std::chrono::nanoseconds;

static constexpr std::array<int64_t, 15> thresholdsNs = {
    1'000, 2'000, 4'000, 8'000, 16'000, 32'000, 64'000, 125'000,
    250'000, 500'000, 1'000'000, 2'000'000, 4'000'000, 8'000'000, 16'000'000,
};

struct Distribution {
    uint64_t count = 0;
    uint64_t sum = 0;
    uint64_t maximum = 0;
    std::array<uint64_t, 16> buckets{};
};

static uint64_t checksum(const Distribution &distribution)
{
    uint64_t value = distribution.count ^ distribution.sum ^ distribution.maximum;
    for (const uint64_t bucket : distribution.buckets) {
        value ^= bucket;
    }
    return value;
}

static void record(Distribution &distribution, int64_t value)
{
    const uint64_t bounded = static_cast<uint64_t>(std::max<int64_t>(value, 0));
    distribution.count++;
    distribution.sum += bounded;
    distribution.maximum = std::max(distribution.maximum, bounded);
    const auto bucket = std::lower_bound(thresholdsNs.begin(), thresholdsNs.end(), value);
    distribution.buckets[static_cast<std::size_t>(bucket - thresholdsNs.begin())]++;
}

template<typename Function>
static double medianCost(uint64_t iterations, Function function)
{
    std::array<double, 7> samples{};
    for (double &sample : samples) {
        const auto start = Clock::now();
        function(iterations);
        const auto end = Clock::now();
        sample = std::chrono::duration_cast<Nanoseconds>(end - start).count() / static_cast<double>(iterations);
    }
    std::sort(samples.begin(), samples.end());
    return samples[samples.size() / 2];
}

int main(int argc, char **argv)
{
    const uint64_t iterations = argc > 1 ? std::strtoull(argv[1], nullptr, 10) : 10'000'000;
    const uint64_t divisor = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 64;
    if (iterations == 0 || divisor == 0) {
        return 2;
    }

    uint64_t clockSink = 0;
    const double clockCost = medianCost(iterations, [&](uint64_t count) {
        uint64_t local = 0;
        for (uint64_t i = 0; i < count; ++i) {
            local ^= static_cast<uint64_t>(Clock::now().time_since_epoch().count());
        }
        clockSink ^= local;
    });

    Distribution fullDistribution;
    const double fullCost = medianCost(iterations, [&](uint64_t count) {
        Distribution local;
        for (uint64_t i = 0; i < count; ++i) {
            record(local, Clock::now().time_since_epoch().count() & 0xffff);
        }
        fullDistribution.sum ^= checksum(local);
    });

    Distribution sampledDistribution;
    const double sampledCost = medianCost(iterations, [&](uint64_t count) {
        Distribution local;
        uint64_t countdown = 1;
        uint64_t exactCounter = 0;
        for (uint64_t i = 0; i < count; ++i) {
            exactCounter++;
            if (--countdown == 0) {
                countdown = divisor;
                record(local, Clock::now().time_since_epoch().count() & 0xffff);
            }
        }
        sampledDistribution.sum ^= checksum(local) + exactCounter;
    });

    std::cout << std::fixed << std::setprecision(2)
              << "iterations=" << iterations << " divisor=" << divisor << "\n"
              << "steady_clock_now_ns_per_call=" << clockCost << "\n"
              << "full_observer_ns_per_event=" << fullCost << "\n"
              << "sampled_observer_ns_per_event=" << sampledCost << "\n"
              << "observer_cost_reduction_percent=" << (100.0 * (1.0 - sampledCost / fullCost)) << "\n"
              << "sink=" << (clockSink ^ fullDistribution.sum ^ sampledDistribution.sum) << "\n";
}
