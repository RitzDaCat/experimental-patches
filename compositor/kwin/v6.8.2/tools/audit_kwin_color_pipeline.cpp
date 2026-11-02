// SPDX-License-Identifier: MIT
// Reconstruct the active PG32UCDP SDR -> HDR/WCG color transforms with KWin's
// own installed color-pipeline implementation. This does not touch DRM state.

#include <kwin/core/colorpipeline.h>
#include <kwin/core/colorspace.h>

#include <QDebug>
#include <QVector3D>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <memory>
#include <type_traits>
#include <vector>

namespace
{

void printVector(const char *label, const QVector3D &value)
{
    std::printf("%-18s %.9f %.9f %.9f\n", label, value.x(), value.y(), value.z());
}

const char *spaceName(KWin::ColorspaceType space)
{
    using KWin::ColorspaceType;
    switch (space) {
    case ColorspaceType::LinearRGB:
        return "linear-rgb";
    case ColorspaceType::NonLinearRGB:
        return "nonlinear-rgb";
    case ColorspaceType::ICtCp:
        return "ictcp";
    case ColorspaceType::AnyNonRGB:
        return "other";
    }
    return "unknown";
}

const char *transferName(KWin::TransferFunction::Type type)
{
    using Type = KWin::TransferFunction::Type;
    switch (type) {
    case Type::sRGB:
        return "sRGB";
    case Type::linear:
        return "linear";
    case Type::PerceptualQuantizer:
        return "PQ";
    case Type::gamma22:
        return "gamma22";
    case Type::BT1886:
        return "BT1886";
    }
    return "unknown";
}

void printPipeline(const char *label, const KWin::ColorPipeline &pipeline)
{
    using namespace KWin;
    std::printf("\n%s: input=[%.9f, %.9f] %s, ops=%zu\n",
                label,
                pipeline.inputRange.min,
                pipeline.inputRange.max,
                spaceName(pipeline.inputSpace),
                pipeline.ops.size());
    for (std::size_t index = 0; index < pipeline.ops.size(); ++index) {
        const ColorOp &op = pipeline.ops[index];
        std::printf("  %zu: [%.9f, %.9f] %s -> [%.9f, %.9f] %s ",
                    index,
                    op.input.min,
                    op.input.max,
                    spaceName(op.inputSpace),
                    op.output.min,
                    op.output.max,
                    spaceName(op.outputSpace));
        std::visit(
            [](const auto &operation) {
                using T = std::decay_t<decltype(operation)>;
                if constexpr (std::is_same_v<T, ColorTransferFunction>) {
                    std::printf("EOTF %s [%.9f, %.9f]", transferName(operation.tf.type), operation.tf.minLuminance, operation.tf.maxLuminance);
                } else if constexpr (std::is_same_v<T, InverseColorTransferFunction>) {
                    std::printf("inverse EOTF %s [%.9f, %.9f]", transferName(operation.tf.type), operation.tf.minLuminance, operation.tf.maxLuminance);
                } else if constexpr (std::is_same_v<T, ColorMatrix>) {
                    std::printf("matrix");
                    for (int row = 0; row < 3; ++row) {
                        std::printf(" [%+.9f %+.9f %+.9f %+.9f]",
                                    operation.mat(row, 0), operation.mat(row, 1), operation.mat(row, 2), operation.mat(row, 3));
                    }
                } else if constexpr (std::is_same_v<T, ColorMultiplier>) {
                    std::printf("multiplier %.9f %.9f %.9f", operation.factors.x(), operation.factors.y(), operation.factors.z());
                } else if constexpr (std::is_same_v<T, ColorTonemapper>) {
                    std::printf("tone mapper");
                } else if constexpr (std::is_same_v<T, ColorClamp>) {
                    std::printf("clamp [%.9f, %.9f]", operation.m_minValue, operation.m_maxValue);
                } else if constexpr (std::is_same_v<T, std::shared_ptr<ColorTransformation>>) {
                    std::printf("1D transformation LUT");
                } else if constexpr (std::is_same_v<T, std::shared_ptr<ColorLUT3D>>) {
                    std::printf("3D LUT");
                }
            },
            op.operation);
        std::printf("\n");
    }
}

template<typename Operation>
void benchmark(const char *label, Operation &&operation)
{
    constexpr std::size_t batchCount = 4096;
    constexpr std::size_t callsPerBatch = 64;
    std::vector<double> nanoseconds;
    nanoseconds.reserve(batchCount);
    std::size_t checksum = 0;
    for (std::size_t batch = 0; batch < batchCount; ++batch) {
        const auto begin = std::chrono::steady_clock::now();
        for (std::size_t call = 0; call < callsPerBatch; ++call) {
            checksum += operation();
        }
        const auto end = std::chrono::steady_clock::now();
        nanoseconds.push_back(std::chrono::duration<double, std::nano>(end - begin).count() / callsPerBatch);
    }
    std::ranges::sort(nanoseconds);
    const auto percentile = [&nanoseconds](double fraction) {
        const std::size_t index = std::min<std::size_t>(nanoseconds.size() - 1, fraction * nanoseconds.size());
        return nanoseconds[index];
    };
    std::printf("\n%s (checksum=%zu)\n", label, checksum);
    std::printf("min=%.3f ns p50=%.3f ns p95=%.3f ns p99=%.3f ns\n",
                nanoseconds.front(), percentile(0.50), percentile(0.95), percentile(0.99));
}

} // namespace

int main()
{
    using namespace KWin;

    // Live DP-2 EDID primaries from /sys/class/drm/card1-DP-2/edid.
    const Colorimetry native(
        xy{0.6767, 0.3212},
        xy{0.2490, 0.6845},
        xy{0.1464, 0.0566},
        xy{0.3134, 0.3291});

    // Live KScreen state: HDR + WCG, 300 nit SDR reference, 420 nit peak
    // override, EDID profile source, and 100% SDR gamut wideness. At 100%,
    // KWin's SDR colorimetry is the display-native gamut.
    const auto originalWire = std::make_shared<ColorDescription>(
        Colorimetry::BT2020,
        TransferFunction(TransferFunction::PerceptualQuantizer),
        300.0,
        0.0001,
        265.047,
        420.0,
        native,
        native);

    // Live Night Light state is 4500 K. Reproduce sampleColorTemperature(),
    // adaptChannelFactors(), and applyNightLight() from KWin.
    const QVector3D blackBody4500(1.0f, 0.86860704f, 0.73688797f);
    const QVector3D sRgbChannelFactors = TransferFunction(TransferFunction::gamma22, 0, 1).encodedToNits(blackBody4500);
    QVector3D adaptedChannelFactors = ColorDescription::sRGB->containerColorimetry().relativeColorimetricTo(originalWire->containerColorimetry()).map(sRgbChannelFactors);
    adaptedChannelFactors.setX(std::max(adaptedChannelFactors.x(), 0.0001f));
    adaptedChannelFactors.setY(std::max(adaptedChannelFactors.y(), 0.0001f));
    adaptedChannelFactors.setZ(std::max(adaptedChannelFactors.z(), 0.0001f));
    const xyY nightWhite = XYZ::fromVector(originalWire->containerColorimetry().toXYZ().map(adaptedChannelFactors)).toxyY();
    const auto adjustedOutput = originalWire->withWhitepoint(nightWhite)->dimmed(nightWhite.Y);
    const auto blending = adjustedOutput->withTransferFunction(
        TransferFunction(TransferFunction::gamma22, 0.0, adjustedOutput->maxHdrLuminance().value()));
    const auto wire = originalWire->withReference(adjustedOutput->referenceLuminance());

    const ColorPipeline plane = ColorPipeline::create(
        ColorDescription::sRGB,
        blending,
        RenderingIntent::Perceptual);
    const ColorPipeline crtc = ColorPipeline::create(
        blending,
        wire,
        RenderingIntent::AbsoluteColorimetricNoAdaptation);
    const ColorPipeline singlePass = ColorPipeline::create(
        ColorDescription::sRGB,
        wire,
        RenderingIntent::Perceptual);

    printVector("4500K sRGB factor", sRgbChannelFactors);
    printVector("adapted factor", adaptedChannelFactors);
    std::printf("night white xyY    %.9f %.9f %.9f\n", nightWhite.x, nightWhite.y, nightWhite.Y);
    std::printf("adjusted reference %.9f nits\n", adjustedOutput->referenceLuminance());
    std::printf("adjusted peak      %.9f nits\n", adjustedOutput->maxHdrLuminance().value());

    printPipeline("plane SDR->blending", plane);
    printPipeline("CRTC blending->wire", crtc);
    printPipeline("single-pass reference", singlePass);

    const std::array<std::pair<const char *, QVector3D>, 8> samples{{
        {"black", QVector3D(0.0f, 0.0f, 0.0f)},
        {"dark gray", QVector3D(0.05f, 0.05f, 0.05f)},
        {"18% encoded", QVector3D(0.18f, 0.18f, 0.18f)},
        {"mid gray", QVector3D(0.5f, 0.5f, 0.5f)},
        {"white", QVector3D(1.0f, 1.0f, 1.0f)},
        {"red", QVector3D(1.0f, 0.0f, 0.0f)},
        {"green", QVector3D(0.0f, 1.0f, 0.0f)},
        {"blue", QVector3D(0.0f, 0.0f, 1.0f)},
    }};

    std::puts("\nencoded input -> plane gamma22 BT.2020 -> final PQ wire");
    for (const auto &[label, input] : samples) {
        const QVector3D planeOutput = plane.evaluate(input);
        const QVector3D wireOutput = crtc.evaluate(planeOutput);
        std::printf("\n%s\n", label);
        printVector("input", input);
        printVector("plane output", planeOutput);
        printVector("wire output", wireOutput);
    }

    double maxEncodedDifference = 0.0;
    QVector3D worstInput;
    constexpr int steps = 32;
    for (int r = 0; r <= steps; ++r) {
        for (int g = 0; g <= steps; ++g) {
            for (int b = 0; b <= steps; ++b) {
                const QVector3D input(r / double(steps), g / double(steps), b / double(steps));
                const QVector3D staged = crtc.evaluate(plane.evaluate(input));
                const QVector3D reference = singlePass.evaluate(input);
                const double difference = std::max({
                    std::abs(staged.x() - reference.x()),
                    std::abs(staged.y() - reference.y()),
                    std::abs(staged.z() - reference.z()),
                });
                if (difference > maxEncodedDifference) {
                    maxEncodedDifference = difference;
                    worstInput = input;
                }
            }
        }
    }

    std::printf("\nmax staged-vs-single-pass encoded difference: %.12f\n", maxEncodedDifference);
    printVector("worst input", worstInput);

    const TransferFunction piecewiseSrgb(TransferFunction::sRGB, 0.0, 1.0);
    std::puts("\npiecewise sRGB CPU roundtrip around the linear/power boundary");
    for (const double encoded : {0.0, 0.01, 0.02, 0.04044, 0.04045, 0.05}) {
        const double linear = piecewiseSrgb.encodedToNits(encoded);
        const double roundtrip = piecewiseSrgb.nitsToEncoded(linear);
        std::printf("encoded=%.8f linear=%.12f roundtrip=%.12f error=%+.12f\n",
                    encoded, linear, roundtrip, roundtrip - encoded);
    }

    benchmark("ColorPipeline::create exact-path batched cost", [&] {
        return ColorPipeline::create(ColorDescription::sRGB, blending, RenderingIntent::Perceptual).ops.size();
    });
    benchmark("three-operation ColorPipeline copy cost", [&] {
        const ColorPipeline copy = plane;
        return copy.ops.size();
    });
    benchmark("three-operation ColorPipeline equality hit cost", [&] {
        return plane == plane;
    });
    benchmark("three-operation ColorPipeline equality miss cost", [&] {
        return plane == crtc;
    });
    return 0;
}
