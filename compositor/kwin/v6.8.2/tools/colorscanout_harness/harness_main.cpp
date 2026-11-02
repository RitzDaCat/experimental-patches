// Offline direct-scanout color-correctness harness for NVIDIA DRM plane
// color pipelines. Links KWin's installed core color math, runs the *real*
// patched matcher (reference/harness/kwin/drm_colorop.cpp), then simulates
// the probed NVIDIA Full hardware chain and compares against the reference
// ColorPipeline over a dense grid. No DRM state is touched.
#include "drm_colorop.h"

#include <kwin/core/colorpipeline.h>
#include <kwin/core/colorspace.h>

#include <QLoggingCategory>
#include <QMatrix4x4>
#include <QVector3D>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>

Q_LOGGING_CATEGORY(KWIN_DRM, "harness.kwin.drm", QtWarningMsg)

using namespace KWin;

namespace
{

struct BlockProps
{
    std::unique_ptr<DrmProperty> data;
    std::unique_ptr<DrmEnumProperty<Named1DLutType>> curve;
    std::unique_ptr<DrmEnumProperty<Lut1DInterpolation>> interp;
    std::unique_ptr<DrmProperty> multiplier;
    std::unique_ptr<DrmProperty> bypass;
};

DrmGpu *gpu()
{
    static DrmGpu gpu;
    return &gpu;
}

// DrmObject instance every mock property hangs off (program() needs a gpu()).
class OwnerObject : public DrmObject
{
public:
    OwnerObject()
        : DrmObject(gpu(), 1, 0)
    {
    }
};

OwnerObject *owner()
{
    static OwnerObject obj;
    return &obj;
}

enum class BlockKind { Matrix3x4, NamedCurve, Lut32, Multiplier };

struct Block
{
    BlockKind kind;
    DrmAbstractColorOp *op = nullptr;
    BlockProps props;
    bool bypassable = false;
    Named1DLutType curveType{};
    uint32_t lutSize = 0;
};

std::unique_ptr<DrmAbstractColorOp> makeMatrix(DrmAbstractColorOp *next, bool bypassable, Block &record)
{
    record.kind = BlockKind::Matrix3x4;
    record.bypassable = bypassable;
    if (bypassable) {
        record.props.bypass = std::make_unique<DrmProperty>(owner(), "BYPASS");
        record.props.bypass->forceValue(1);
    }
    record.props.data = std::make_unique<DrmProperty>(owner(), "DATA");
    auto result = std::make_unique<Matrix3x4ColorOp>(next, record.props.data.get(), bypassable ? record.props.bypass.get() : nullptr);
    return result;
}

std::unique_ptr<DrmAbstractColorOp> makeNamedCurve(DrmAbstractColorOp *next, Named1DLutType type, bool bypassable, Block &record)
{
    record.kind = BlockKind::NamedCurve;
    record.bypassable = bypassable;
    record.curveType = type;
    record.props.curve = std::make_unique<DrmEnumProperty<Named1DLutType>>(owner(), "CURVE_1D_TYPE");
    record.props.curve->forceAllowed({static_cast<uint64_t>(type)});
    record.props.curve->forceValue(static_cast<uint64_t>(type));
    if (bypassable) {
        record.props.bypass = std::make_unique<DrmProperty>(owner(), "BYPASS");
        record.props.bypass->forceValue(1);
    }
    return std::make_unique<DrmNamed1DLut>(next, record.props.curve.get(), bypassable ? record.props.bypass.get() : nullptr);
}

std::unique_ptr<DrmAbstractColorOp> makeLut32(DrmAbstractColorOp *next, uint32_t size, Block &record)
{
    record.kind = BlockKind::Lut32;
    record.bypassable = true;
    record.lutSize = size;
    record.props.interp = std::make_unique<DrmEnumProperty<Lut1DInterpolation>>(owner(), "LUT1D_INTERPOLATION");
    record.props.data = std::make_unique<DrmProperty>(owner(), "DATA");
    record.props.bypass = std::make_unique<DrmProperty>(owner(), "BYPASS");
    record.props.bypass->forceValue(1);
    return std::make_unique<DrmLutColorOp32>(next, record.props.data.get(), record.props.interp.get(), size, record.props.bypass.get());
}

std::unique_ptr<DrmAbstractColorOp> makeMultiplier(DrmAbstractColorOp *next, Block &record)
{
    record.kind = BlockKind::Multiplier;
    record.bypassable = true;
    record.props.multiplier = std::make_unique<DrmProperty>(owner(), "MULTIPLIER");
    record.props.bypass = std::make_unique<DrmProperty>(owner(), "BYPASS");
    record.props.bypass->forceValue(1);
    return std::make_unique<DrmMultiplier>(next, record.props.multiplier.get(), record.props.bypass.get());
}

// NVIDIA Full graph as probed live on 610.57.04 (2026-08-23):
// M58 C63(PQ125 EOTF) LUT68 Mult75 M80 N85(PQ125 Inv, mandatory)
// M89 LUT94 M101 N106(PQ125 EOTF, mandatory) M110
struct Chain
{
    std::vector<Block> blocks;
    std::vector<std::unique_ptr<DrmAbstractColorOp>> ops;
    DrmAbstractColorOp *head = nullptr;

    void build()
    {
        blocks.resize(11);
        ops.resize(11);
        DrmAbstractColorOp *rawNext = nullptr;
        // build back to front; block[0] is first in scanout order
        for (int i = 10; i >= 0; --i) {
            switch (i) {
            case 0:
                ops[i] = makeMatrix(rawNext, true, blocks[i]);
                break;
            case 1:
                ops[i] = makeNamedCurve(rawNext, Named1DLutType::PQ_125, true, blocks[i]);
                break;
            case 2:
                ops[i] = makeLut32(rawNext, 1024, blocks[i]);
                break;
            case 3:
                ops[i] = makeMultiplier(rawNext, blocks[i]);
                break;
            case 4:
                ops[i] = makeMatrix(rawNext, true, blocks[i]);
                break;
            case 5:
                ops[i] = makeNamedCurve(rawNext, Named1DLutType::PQ_125_Inverse, false, blocks[i]);
                break;
            case 6:
                ops[i] = makeMatrix(rawNext, true, blocks[i]);
                break;
            case 7:
                ops[i] = makeLut32(rawNext, 1024, blocks[i]);
                break;
            case 8:
                ops[i] = makeMatrix(rawNext, true, blocks[i]);
                break;
            case 9:
                ops[i] = makeNamedCurve(rawNext, Named1DLutType::PQ_125, false, blocks[i]);
                break;
            case 10:
                ops[i] = makeMatrix(rawNext, true, blocks[i]);
                break;
            }
            if (!ops[i]) {
                std::fprintf(stderr, "FATAL: chain lost ownership at %d\n", i);
                exit(1);
            }
            rawNext = ops[i].get();
        }
        head = ops.front().get();
    }
};

// ------------------------------------------------------------- live config

struct Config
{
    const char *label;
    bool nightLight;
};

// Reproduces tools/audit_kwin_color_pipeline.cpp live-state reconstruction.
std::shared_ptr<ColorDescription> wireDescription(bool nightLight)
{
    const Colorimetry native(
        xy{0.6767, 0.3212},
        xy{0.2490, 0.6845},
        xy{0.1464, 0.0566},
        xy{0.3134, 0.3291});

    const auto originalWire = std::make_shared<ColorDescription>(
        Colorimetry::BT2020,
        TransferFunction(TransferFunction::PerceptualQuantizer),
        300.0,
        0.0001,
        265.047,
        420.0,
        native,
        native);

    if (!nightLight) {
        return originalWire;
    }

    const QVector3D blackBody4500(1.0f, 0.86860704f, 0.73688797f);
    const QVector3D sRgbChannelFactors = TransferFunction(TransferFunction::gamma22, 0, 1).encodedToNits(blackBody4500);
    QVector3D adaptedChannelFactors = ColorDescription::sRGB->containerColorimetry().relativeColorimetricTo(originalWire->containerColorimetry()).map(sRgbChannelFactors);
    adaptedChannelFactors.setX(std::max(adaptedChannelFactors.x(), 0.0001f));
    adaptedChannelFactors.setY(std::max(adaptedChannelFactors.y(), 0.0001f));
    adaptedChannelFactors.setZ(std::max(adaptedChannelFactors.z(), 0.0001f));
    const xyY nightWhite = XYZ::fromVector(originalWire->containerColorimetry().toXYZ().map(adaptedChannelFactors)).toxyY();
    const auto adjustedOutput = originalWire->withWhitepoint(nightWhite)->dimmed(nightWhite.Y);
    return adjustedOutput;
}

// ------------------------------------------------------- hardware simulation

double fixedToDouble(uint64_t raw)
{
    // S31.32 sign-magnitude
    const double magnitude = static_cast<double>(raw & ~(1ull << 63)) / (1ull << 32);
    return (raw & (1ull << 63)) ? -magnitude : magnitude;
}

// Harness configuration, set from argv before any simulation.
struct HarnessConfig
{
    // Linear-domain maximum KWin assumes for the mandatory PQ stages.
    // 125 = DRM UAPI PQ_125 convention (what patch 0016 models).
    // 1 = NVIDIA internal convention (10000 nits -> 1.0, per the driver's
    // own comment; the commit path applies no bridge for CSC0LUT/CSC1LUT).
    double cscPqMax = 125.0;
    bool quantizeMatrices = true; // S31.32 -> S31.16 truncation in ctm_val_to_csc_val
    bool quantizeTmoUnorm16 = true; // TMO LUT surface is UNORM16
    bool quantizeIlutFp16 = true; // ILUT surface is FP16
};
HarnessConfig g_config;

float quantizeFp16(float v)
{
    return static_cast<float>(static_cast<_Float16>(v));
}

float quantizeUnorm16(float v)
{
    return std::round(std::clamp(v, 0.0f, 1.0f) * 65535.0f) / 65535.0f;
}

// ctm_val_to_csc_val: S31.32 sign-magnitude, magnitude >> 16 -> S15.16-ish
double quantizeMatrixEntry(double v)
{
    const bool negative = v < 0;
    uint64_t magnitude = static_cast<uint64_t>(std::abs(v) * (1ull << 32));
    magnitude >>= 16;
    const double result = static_cast<double>(magnitude) / (1ull << 16);
    return negative ? -result : result;
}

// Both PQ conventions take ENCODED [0,1] input on the EOTF; they differ in
// the linear output scale: UAPI PQ_125 -> [0,125], NVIDIA internal -> [0,1]
// (10000 nits map to 1.0). The inverse accordingly takes [0,scale] input.
float curveApply(Named1DLutType type, float x, uint64_t &clamps)
{
    const float scale = static_cast<float>(g_config.cscPqMax);
    switch (type) {
    case Named1DLutType::PQ_125: {
        if (x < 0 || x > 1) {
            clamps++;
        }
        x = std::clamp(x, 0.0f, 1.0f);
        return TransferFunction(TransferFunction::PerceptualQuantizer, 0, scale).encodedToNits(x);
    }
    case Named1DLutType::PQ_125_Inverse: {
        if (x < 0 || x > scale) {
            clamps++;
        }
        x = std::clamp(x, 0.0f, scale);
        return TransferFunction(TransferFunction::PerceptualQuantizer, 0, scale).nitsToEncoded(x);
    }
    default:
        std::fprintf(stderr, "unexpected curve %d\n", int(type));
        exit(2);
    }
}

struct SimState
{
    uint64_t clamps = 0;
};

QVector3D simulate(const Chain &chain, QVector3D v, SimState &state)
{
    for (size_t i = 0; i < chain.blocks.size(); ++i) {
        const Block &block = chain.blocks[i];
        const auto *bypassEntry = DrmAtomicCommit::entry(block.props.bypass.get());
        const bool bypassed = block.bypassable && bypassEntry && bypassEntry->hasValue && bypassEntry->value == 1;
        if (bypassed) {
            continue;
        }
        switch (block.kind) {
        case BlockKind::NamedCurve: {
            const auto *curveEntry = DrmAtomicCommit::entry(block.props.curve.get());
            if (!curveEntry || !curveEntry->hasValue) {
                std::fprintf(stderr, "FATAL: mandatory curve block %zu has no programmed enum\n", i);
                exit(3);
            }
            const auto type = static_cast<Named1DLutType>(curveEntry->value);
            v.setX(curveApply(type, v.x(), state.clamps));
            v.setY(curveApply(type, v.y(), state.clamps));
            v.setZ(curveApply(type, v.z(), state.clamps));
            break;
        }
        case BlockKind::Lut32: {
            const auto *blobEntry = DrmAtomicCommit::entry(block.props.data.get());
            if (!blobEntry || !blobEntry->blob) {
                std::fprintf(stderr, "FATAL: LUT block %zu has no programmed blob\n", i);
                exit(3);
            }
            const auto *components = reinterpret_cast<const LutComponent32 *>(blobEntry->blob->data.data());
            const size_t n = blobEntry->blob->data.size() / sizeof(LutComponent32);
            auto sample = [&](float x) -> float {
                if (x < 0 || x > 1) {
                    state.clamps++;
                }
                const double t = std::clamp<double>(x, 0.0, 1.0) * (n - 1);
                const size_t idx = std::min<size_t>(t, n - 2);
                const double frac = t - idx;
                auto channel = [&](uint32_t lo, uint32_t hi) {
                    return (lo / 4294967295.0) * (1 - frac) + (hi / 4294967295.0) * frac;
                };
                return channel(components[idx].red, components[idx + 1].red); // caller picks channel via vector trick below
            };
            // KWin builds one table applied identically to each channel;
            // take red as the table. Hardware surface quantization:
            // TMO LUT surface is UNORM16, ILUT surface is FP16.
            auto sampleChannel = [&](float x) -> float {
                if (x < 0 || x > 1) {
                    state.clamps++;
                }
                const double t = std::clamp<double>(x, 0.0, 1.0) * (n - 1);
                const size_t idx = std::min<size_t>(size_t(t), n - 2);
                const double frac = t - idx;
                auto entry = [&](const LutComponent32 &c) {
                    const double linear = c.red / 4294967295.0;
                    if (i == 7 && g_config.quantizeTmoUnorm16) {
                        return double(quantizeUnorm16(float(linear)));
                    }
                    if (i == 2 && g_config.quantizeIlutFp16) {
                        return double(quantizeFp16(float(linear)));
                    }
                    return linear;
                };
                return entry(components[idx]) * (1 - frac) + entry(components[idx + 1]) * frac;
            };
            v = QVector3D(sampleChannel(v.x()), sampleChannel(v.y()), sampleChannel(v.z()));
            break;
        }
        case BlockKind::Multiplier: {
            const auto *multEntry = DrmAtomicCommit::entry(block.props.multiplier.get());
            if (!multEntry || !multEntry->hasValue) {
                continue; // bypassed without property write shouldn't happen; treat as identity
            }
            const double factor = fixedToDouble(multEntry->value);
            v = QVector3D(v.x() * factor, v.y() * factor, v.z() * factor);
            break;
        }
        case BlockKind::Matrix3x4: {
            const auto *blobEntry = DrmAtomicCommit::entry(block.props.data.get());
            if (!blobEntry || !blobEntry->blob || blobEntry->blob->data.size() != sizeof(uint64_t) * 12) {
                continue; // treated as bypassed
            }
            QMatrix4x4 m;
            uint64_t raw[12];
            memcpy(raw, blobEntry->blob->data.data(), sizeof(raw));
            auto entry = [&](uint64_t v) {
                return static_cast<float>(g_config.quantizeMatrices ? quantizeMatrixEntry(fixedToDouble(v)) : fixedToDouble(v));
            };
            m(0, 0) = entry(raw[0]);
            m(0, 1) = entry(raw[1]);
            m(0, 2) = entry(raw[2]);
            m(0, 3) = entry(raw[3]);
            m(1, 0) = entry(raw[4]);
            m(1, 1) = entry(raw[5]);
            m(1, 2) = entry(raw[6]);
            m(1, 3) = entry(raw[7]);
            m(2, 0) = entry(raw[8]);
            m(2, 1) = entry(raw[9]);
            m(2, 2) = entry(raw[10]);
            m(2, 3) = entry(raw[11]);
            v = (m * QVector4D(v, 1.0)).toVector3DAffine();
            break;
        }
        }
    }
    return v;
}

// ------------------------------------------------------------------ report

struct Stats
{
    double max = 0;
    double sum = 0;
    double sumSq = 0;
    uint64_t count = 0;
    double worstVal[3] = {0, 0, 0};
    QVector3D worstInput;

    void add(double err, const QVector3D &input)
    {
        max = std::max(max, err);
        sum += err;
        sumSq += err * err;
        count++;
        if (err >= max) {
            worstVal[0] = err;
            worstInput = input;
        }
    }
    double mean() const { return count ? sum / count : 0; }
    double rms() const { return count ? std::sqrt(sumSq / count) : 0; }
};

int runConfig(const Config &config)
{
    std::printf("=== config: %s ===\n", config.label);
    Chain chain;
    chain.build();

    const auto adjusted = wireDescription(config.nightLight);
    const auto blending = adjusted->withTransferFunction(
        TransferFunction(TransferFunction::gamma22, 0.0, adjusted->maxHdrLuminance().value()));

    const ColorPipeline planePipeline = ColorPipeline::create(ColorDescription::sRGB, blending, RenderingIntent::Perceptual);
    std::printf("requested pipeline ops: %zu\n", planePipeline.ops.size());

    DrmAtomicCommit commit(gpu());
    const bool matched = chain.head->matchPipeline(&commit, planePipeline);
    std::printf("matchPipeline: %s\n", matched ? "SUCCESS" : "FAIL");

    // dump programmed state
    for (size_t i = 0; i < chain.blocks.size(); ++i) {
        const Block &b = chain.blocks[i];
        const char *kindName = b.kind == BlockKind::Matrix3x4 ? "matrix" : b.kind == BlockKind::NamedCurve ? "curve"
            : b.kind == BlockKind::Lut32                                    ? "lut1024"
                                                                            : "multiplier";
        const auto *bypassEntry = DrmAtomicCommit::entry(b.props.bypass.get());
        const bool bypassed = b.bypassable && bypassEntry && bypassEntry->hasValue && bypassEntry->value == 1;
        std::printf("  block[%2zu] %-10s %s", i, kindName, bypassed ? "BYPASSED" : "programmed");
        if (b.kind == BlockKind::NamedCurve && !bypassed) {
            if (const auto *e = DrmAtomicCommit::entry(b.props.curve.get()); e && e->hasValue) {
                std::printf(" enum=%llu", (unsigned long long)e->value);
            }
        }
        std::printf("\n");
    }

    if (!matched) {
        std::printf("\n");
        return 1;
    }

    // simulate vs reference
    Stats encStats[3];
    Stats linStats[3];
    SimState state;
    constexpr int N = 48;
    const float peak = adjusted->maxHdrLuminance().value();
    const TransferFunction blendTf(TransferFunction::gamma22, 0.0, peak);

    for (int r = 0; r < N; ++r) {
        for (int g = 0; g < N; ++g) {
            for (int b = 0; b < N; ++b) {
                const QVector3D input(r / (N - 1.0f), g / (N - 1.0f), b / (N - 1.0f));
                const QVector3D ref = planePipeline.evaluate(input);
                const QVector3D hw = simulate(chain, input, state);
                const QVector3D encErr(hw.x() - ref.x(), hw.y() - ref.y(), hw.z() - ref.z());
                const QVector3D linErr(blendTf.encodedToNits(hw).x() - blendTf.encodedToNits(ref).x(),
                                       blendTf.encodedToNits(hw).y() - blendTf.encodedToNits(ref).y(),
                                       blendTf.encodedToNits(hw).z() - blendTf.encodedToNits(ref).z());
                const double encMax = std::max({std::abs(encErr.x()), std::abs(encErr.y()), std::abs(encErr.z())});
                const double linMax = std::max({std::abs(linErr.x()), std::abs(linErr.y()), std::abs(linErr.z())});
                for (int c = 0; c < 3; ++c) {
                    encStats[c].add(std::abs(encErr[c]), input);
                    linStats[c].add(std::abs(linErr[c]), input);
                }
                (void)encMax;
                (void)linMax;
            }
        }
    }

    const char *names[3] = {"R", "G", "B"};
    for (int c = 0; c < 3; ++c) {
        std::printf("  encoded err %s: mean %.6f rms %.6f max %.6f\n", names[c], encStats[c].mean(), encStats[c].rms(), encStats[c].max);
    }
    for (int c = 0; c < 3; ++c) {
        std::printf("  linear   err %s: mean %.3f nits rms %.3f nits max %.3f nits\n", names[c], linStats[c].mean(), linStats[c].rms(), linStats[c].max);
    }
    // purple metric: green deficit relative to R/B in linear domain
    const double purpleMean = (linStats[0].mean() + linStats[2].mean()) / 2 - linStats[1].mean();
    const double purpleMax = (linStats[0].max + linStats[2].max) / 2 - linStats[1].max;
    std::printf("  purple metric (mean): %+.4f nits, (max-based): %+.4f nits\n", purpleMean, purpleMax);
    std::printf("  hardware-domain clamp events over grid: %llu\n", (unsigned long long)state.clamps);
    std::printf("  worst encoded-G input: %.3f %.3f %.3f\n",
                encStats[1].worstInput.x(), encStats[1].worstInput.y(), encStats[1].worstInput.z());
    std::printf("\n");
    return matched ? 0 : 1;
}

}
int main(int argc, char **argv)
{
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    if (argc > 1) {
        g_config.cscPqMax = std::atof(argv[1]);
    }
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "no-matrix-quant") == 0) {
            g_config.quantizeMatrices = false;
        } else if (std::strcmp(argv[i], "no-tmo-quant") == 0) {
            g_config.quantizeTmoUnorm16 = false;
        } else if (std::strcmp(argv[i], "no-ilut-quant") == 0) {
            g_config.quantizeIlutFp16 = false;
        }
    }
    const QByteArray assumed = qgetenv("KWIN_DRM_NVIDIA_CSC_PQ_SCALE");
    std::printf("hardware model: CSC PQ max = %.3f | KWin assumes: %s | matrix quant %s, tmo quant %s, ilut quant %s\n\n",
                g_config.cscPqMax,
                assumed == "1" ? "1 (internal convention)" : "125 (UAPI, default)",
                g_config.quantizeMatrices ? "on" : "off",
                g_config.quantizeTmoUnorm16 ? "on" : "off",
                g_config.quantizeIlutFp16 ? "on" : "off");
    const Config configs[] = {
        {"night light off", false},
        {"night light 4500K", true},
    };
    int failures = 0;
    for (const auto &config : configs) {
        failures += runConfig(config) == 1;
    }
    return failures == 2 ? 1 : 0;
}
