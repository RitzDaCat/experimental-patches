#include "core/outputlayer.h"

#include <QCoreApplication>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <vector>

using namespace KWin;

class BenchmarkOutputLayer final : public OutputLayer
{
public:
    BenchmarkOutputLayer()
        : OutputLayer(nullptr, OutputLayerType::Primary)
    {
    }

    DrmDevice *scanoutDevice() const override
    {
        return nullptr;
    }

    FormatModifierMap supportedDrmFormats() const override
    {
        return {};
    }

    void releaseBuffers() override
    {
    }

protected:
    std::optional<OutputLayerBeginFrameInfo> doBeginFrame() override
    {
        return std::nullopt;
    }

    bool doEndFrame(const Region &, const Region &, OutputFrame *) override
    {
        return false;
    }
};

struct Distribution
{
    double minimum;
    double p50;
    double p95;
    double p99;
};

template<typename Operation>
static Distribution benchmark(Operation operation)
{
    constexpr size_t samples = 512;
    constexpr size_t batch = 4096;
    std::vector<double> durations;
    durations.reserve(samples);
    for (size_t sample = 0; sample < samples; ++sample) {
        const auto start = std::chrono::steady_clock::now();
        for (size_t i = 0; i < batch; ++i) {
            operation();
        }
        const auto end = std::chrono::steady_clock::now();
        durations.push_back(std::chrono::duration<double, std::nano>(end - start).count() / batch);
    }
    std::ranges::sort(durations);
    return Distribution{
        .minimum = durations.front(),
        .p50 = durations[samples * 50 / 100],
        .p95 = durations[samples * 95 / 100],
        .p99 = durations[samples * 99 / 100],
    };
}

static void printDistribution(const char *name, const Distribution &distribution)
{
    std::printf("%-42s min=%7.3f ns p50=%7.3f ns p95=%7.3f ns p99=%7.3f ns\n",
                name,
                distribution.minimum,
                distribution.p50,
                distribution.p95,
                distribution.p99);
}

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    BenchmarkOutputLayer layer;
    const auto source = ColorDescription::sRGB;
    const auto destination = std::make_shared<ColorDescription>(
        Colorimetry::BT2020,
        TransferFunction(TransferFunction::gamma22, 0.0001, 325.125081539),
        232.232201099,
        0.0001,
        325.125081539,
        325.125081539);
    const ColorPipeline identity;

    layer.setDirectScanoutColor(source, destination, RenderingIntent::Perceptual);
    const Distribution stableScanout = benchmark([&] {
        layer.setDirectScanoutColor(source, destination, RenderingIntent::Perceptual);
    });

    const Distribution fallbackToScanout = benchmark([&] {
        layer.setColor(destination, RenderingIntent::AbsoluteColorimetricNoAdaptation, identity);
        layer.setDirectScanoutColor(source, destination, RenderingIntent::Perceptual);
    });

    layer.setColorWithHdrMetadata(destination, 232.232201099, 325.125081539, RenderingIntent::AbsoluteColorimetricNoAdaptation, identity);
    const ColorDescription *const cachedMetadata = layer.colorDescription().get();
    const Distribution stableHdrMetadata = benchmark([&] {
        layer.setColorWithHdrMetadata(destination, 232.232201099, 325.125081539, RenderingIntent::AbsoluteColorimetricNoAdaptation, identity);
    });
    if (layer.colorDescription().get() != cachedMetadata) {
        std::fputs("HDR metadata cache did not retain the stable object\n", stderr);
        return 1;
    }

    printDistribution("stable direct-scanout cache hit", stableScanout);
    printDistribution("fallback then cached scanout restore", fallbackToScanout);
    printDistribution("stable HDR metadata cache hit", stableHdrMetadata);
    return 0;
}
