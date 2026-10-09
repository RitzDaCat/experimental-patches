/*
    SPDX-FileCopyrightText: 2022 Vlad Zahorodnii <vlad.zahorodnii@kde.org>

    SPDX-License-Identifier: GPL-2.0-or-later
*/

#include "outputlayer.h"
#include "scene/surfaceitem.h"
#include "scene/surfaceitem_wayland.h"
#include "wayland/surface.h"

#include <QDebug>
#include <fstream>
#include <optional>
#include <sys/utsname.h>

namespace KWin
{

static bool colorLatencyCaptureEnabled()
{
    if (qEnvironmentVariableIntValue("KWIN_LATENCY_CAPTURE") != 1) {
        return false;
    }
    const QByteArray expectedRelease = qgetenv("KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE");
    struct utsname systemInfo;
    return !expectedRelease.isEmpty() && uname(&systemInfo) == 0 && expectedRelease == systemInfo.release;
}

static const bool s_colorLatencyCaptureEnabled = colorLatencyCaptureEnabled();
static std::optional<std::fstream> s_colorPipelineTelemetry;
static uint64_t s_colorPipelineSequence = 0;

template<typename T>
static QString describeColorValue(const T &value)
{
    QString result;
    QDebug debug(&result);
    debug.noquote().nospace() << value;
    return result;
}

static void writeColorPipelineTelemetry(const std::shared_ptr<ColorDescription> &source,
                                        const std::shared_ptr<ColorDescription> &destination,
                                        RenderingIntent intent, ColorPipeline::InputType inputType,
                                        const ColorPipeline &pipeline,
                                        std::chrono::nanoseconds constructionDuration)
{
    if (!s_colorLatencyCaptureEnabled) {
        return;
    }
    if (!s_colorPipelineTelemetry) {
        s_colorPipelineTelemetry.emplace("kwin color pipeline.log", std::ios::out);
    }
    const auto timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    *s_colorPipelineTelemetry
        << "record=" << ++s_colorPipelineSequence << " timestamp_ns=" << timestamp
        << " duration_ns=" << constructionDuration.count()
        << " intent=" << static_cast<unsigned int>(intent)
        << " input_type=" << static_cast<unsigned int>(inputType) << "\n"
        << "source=" << qPrintable(describeColorValue(*source)) << "\n"
        << "destination=" << qPrintable(describeColorValue(*destination)) << "\n"
        << "requested_pipeline=" << qPrintable(describeColorValue(pipeline)) << "\n"
        << "end_record\n";
    s_colorPipelineTelemetry->flush();
}

OutputLayer::OutputLayer(BackendOutput *output, OutputLayerType type)
    : m_type(type)
    , m_output(output)
    , m_renderLoop(output ? output->renderLoop() : nullptr)
    , m_zpos(type == OutputLayerType::Primary ? 0 : 1)
    , m_minZpos(m_zpos)
    , m_maxZpos(m_zpos)
{
}

OutputLayer::OutputLayer(BackendOutput *output, OutputLayerType type, int zpos, int minZpos, int maxZpos)
    : m_type(type)
    , m_output(output)
    , m_renderLoop(output ? output->renderLoop() : nullptr)
    , m_zpos(zpos)
    , m_minZpos(minZpos)
    , m_maxZpos(maxZpos)
{
}

OutputLayerType OutputLayer::type() const
{
    return m_type;
}

void OutputLayer::setRenderLoop(RenderLoop *loop)
{
    m_renderLoop = loop;
}

void OutputLayer::setOutput(BackendOutput *output)
{
    m_output = output;
    if (output) {
        m_renderLoop = output->renderLoop();
        addDeviceRepaint(Region::infinite());
    } else {
        m_renderLoop = nullptr;
    }
}

QPointF OutputLayer::hotspot() const
{
    return m_hotspot;
}

void OutputLayer::setHotspot(const QPointF &hotspot)
{
    m_hotspot = hotspot;
}

QList<QSize> OutputLayer::recommendedSizes() const
{
    return {};
}

Region OutputLayer::deviceRepaints() const
{
    return m_repaints;
}

void OutputLayer::scheduleRepaint(Item *item)
{
    if (!m_output) {
        return;
    }
    m_repaintScheduled = true;
    if (m_renderLoop) {
        m_renderLoop->scheduleRepaint(item, this);
    }
    Q_EMIT repaintScheduled();
}

void OutputLayer::addDeviceRepaint(const Region &region)
{
    if (region.isEmpty() || !m_output) {
        return;
    }
    m_repaints += region;
    if (m_renderLoop) {
        m_renderLoop->scheduleRepaint(nullptr, this);
    }
    Q_EMIT repaintScheduled();
}

void OutputLayer::resetRepaints()
{
    m_repaintScheduled = false;
    m_repaints = Region();
}

bool OutputLayer::needsRepaint() const
{
    return m_repaintScheduled || !m_repaints.isEmpty();
}

bool OutputLayer::earlyScanoutChecks()
{
    return false;
}

bool OutputLayer::importScanoutBuffer(GraphicsBuffer *buffer, const std::shared_ptr<OutputFrame> &frame)
{
    return false;
}

std::optional<OutputLayerBeginFrameInfo> OutputLayer::beginFrame()
{
    return doBeginFrame();
}

bool OutputLayer::endFrame(const Region &renderedDeviceRegion, const Region &damagedDeviceRegion, OutputFrame *frame)
{
    return doEndFrame(renderedDeviceRegion, damagedDeviceRegion, frame);
}

void OutputLayer::setScanoutCandidate(SurfaceItem *item)
{
    if (m_scanoutCandidate && item != m_scanoutCandidate) {
        m_scanoutCandidate->setScanoutHint(nullptr, {});
    }
    m_scanoutCandidate = item;
}

void OutputLayer::setEnabled(bool enable)
{
    m_enabled = enable;
    if (!enable) {
        releaseBuffers();
    }
}

bool OutputLayer::isEnabled() const
{
    return m_enabled;
}

RectF OutputLayer::sourceRect() const
{
    return m_sourceRect;
}

void OutputLayer::setSourceRect(const RectF &rect)
{
    m_sourceRect = rect;
}

OutputTransform OutputLayer::offloadTransform() const
{
    return m_offloadTransform;
}

OutputTransform OutputLayer::bufferTransform() const
{
    return m_bufferTransform;
}

Rect OutputLayer::targetRect() const
{
    return m_targetRect;
}

void OutputLayer::setTargetRect(const Rect &rect)
{
    m_targetRect = rect;
}

FormatModifierMap OutputLayer::supportedAsyncDrmFormats() const
{
    return supportedDrmFormats();
}

void OutputLayer::setOffloadTransform(const OutputTransform &transform)
{
    m_offloadTransform = transform;
}

void OutputLayer::setBufferTransform(const OutputTransform &transform)
{
    m_bufferTransform = transform;
}

const ColorPipeline &OutputLayer::colorPipeline() const
{
    return m_colorPipeline;
}

const std::shared_ptr<ColorDescription> &OutputLayer::colorDescription() const
{
    return m_color;
}

RenderingIntent OutputLayer::renderIntent() const
{
    return m_renderingIntent;
}

void OutputLayer::setColor(const std::shared_ptr<ColorDescription> &color, RenderingIntent intent, const ColorPipeline &pipeline)
{
    if (m_color.get() != color.get()) {
        m_color = color;
    }
    m_renderingIntent = intent;
    m_colorPipeline = pipeline;
    m_directScanoutColorCache.active = false;
}

void OutputLayer::setDirectScanoutColor(const std::shared_ptr<ColorDescription> &source, const std::shared_ptr<ColorDescription> &destination, RenderingIntent intent, ColorPipeline::InputType inputType)
{
    const bool cacheHit = m_directScanoutColorCache.valid
        && m_directScanoutColorCache.source.get() == source.get()
        && m_directScanoutColorCache.destination.get() == destination.get()
        && m_directScanoutColorCache.intent == intent
        && m_directScanoutColorCache.inputType == inputType;
    if (!cacheHit) {
        const auto telemetryStart = s_colorLatencyCaptureEnabled ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
        m_directScanoutColorCache.source = source;
        m_directScanoutColorCache.destination = destination;
        m_directScanoutColorCache.intent = intent;
        m_directScanoutColorCache.inputType = inputType;
        m_directScanoutColorCache.pipeline = ColorPipeline::create(source, destination, intent, inputType);
        m_directScanoutColorCache.valid = true;
        m_directScanoutColorCache.active = false;
        writeColorPipelineTelemetry(source, destination, intent, inputType, m_directScanoutColorCache.pipeline,
                                    s_colorLatencyCaptureEnabled ? std::chrono::steady_clock::now() - telemetryStart : std::chrono::nanoseconds::zero());
    }
    if (!m_directScanoutColorCache.active) {
        m_colorPipeline = m_directScanoutColorCache.pipeline;
        m_directScanoutColorCache.active = true;
    }
    if (m_color.get() != source.get()) {
        m_color = source;
    }
    m_renderingIntent = intent;
}

void OutputLayer::setColorWithHdrMetadata(const std::shared_ptr<ColorDescription> &base, double maxAverageLuminance, double maxLuminance, RenderingIntent intent, const ColorPipeline &pipeline)
{
    const bool cacheHit = m_hdrMetadataColorCache.valid
        && m_hdrMetadataColorCache.base.get() == base.get()
        && m_hdrMetadataColorCache.maxAverageLuminance == maxAverageLuminance
        && m_hdrMetadataColorCache.maxLuminance == maxLuminance;
    if (!cacheHit) {
        m_hdrMetadataColorCache.base = base;
        m_hdrMetadataColorCache.maxAverageLuminance = maxAverageLuminance;
        m_hdrMetadataColorCache.maxLuminance = maxLuminance;
        m_hdrMetadataColorCache.result = base->withHdrMetadata(maxAverageLuminance, maxLuminance);
        m_hdrMetadataColorCache.valid = true;
    }
    setColor(m_hdrMetadataColorCache.result, intent, pipeline);
}

bool OutputLayer::preparePresentationTest()
{
    return true;
}

void OutputLayer::setRequiredAlphaBits(uint32_t bits)
{
    m_requiredAlphaBits = bits;
}

void OutputLayer::setZpos(int zpos)
{
    Q_ASSERT(zpos >= m_minZpos);
    Q_ASSERT(zpos <= m_maxZpos);
    m_zpos = zpos;
}

int OutputLayer::zpos() const
{
    return m_zpos;
}

int OutputLayer::minZpos() const
{
    return m_minZpos;
}

int OutputLayer::maxZpos() const
{
    return m_maxZpos;
}

QList<FormatInfo> OutputLayer::filterAndSortFormats(const FormatModifierMap &formats, uint32_t requiredAlphaBits, BackendOutput::ColorPowerTradeoff tradeoff)
{
    QList<FormatInfo> ret;
    for (auto it = formats.begin(); it != formats.end(); it++) {
        const auto info = FormatInfo::get(it.key());
        if (!info) {
            continue;
        }
        if (info->alphaBits < requiredAlphaBits) {
            continue;
        }
        if (info->bitsPerColor < 8) {
            continue;
        }
        ret.push_back(*info);
    }
    std::ranges::sort(ret, [tradeoff](const FormatInfo &before, const FormatInfo &after) {
        if (tradeoff == BackendOutput::ColorPowerTradeoff::PreferAccuracy && before.bitsPerColor != after.bitsPerColor) {
            return before.bitsPerColor > after.bitsPerColor;
        }
        if (before.floatingPoint != after.floatingPoint) {
            return !before.floatingPoint;
        }
        const bool beforeHasAlpha = before.alphaBits != 0;
        const bool afterHasAlpha = after.alphaBits != 0;
        if (beforeHasAlpha != afterHasAlpha) {
            return beforeHasAlpha;
        }
        if (before.bitsPerPixel != after.bitsPerPixel) {
            return before.bitsPerPixel < after.bitsPerPixel;
        }
        return before.bitsPerColor > after.bitsPerColor;
    });
    return ret;
}

} // namespace KWin

#include "moc_outputlayer.cpp"
