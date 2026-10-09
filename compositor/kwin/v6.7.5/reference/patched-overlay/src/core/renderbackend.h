/*
    SPDX-FileCopyrightText: 2021 Vlad Zahorodnii <vlad.zahorodnii@kde.org>

    SPDX-License-Identifier: GPL-2.0-or-later
*/

#pragma once

#include "core/drm_formats.h"
#include "core/rendertarget.h"
#include "effect/globals.h"
#include "utils/filedescriptor.h"

#include <QObject>
#include <QPointer>
#include <cstdint>
#include <memory>

namespace KWin
{

class GraphicsBuffer;
class LogicalOutput;
class OutputLayer;
class PresentationFeedback;
class RenderLoop;
class DrmDevice;
class SyncTimeline;

class PresentationFeedback
{
public:
    explicit PresentationFeedback() = default;
    PresentationFeedback(const PresentationFeedback &copy) = delete;
    PresentationFeedback(PresentationFeedback &&move) = default;
    virtual ~PresentationFeedback() = default;

    virtual void presented(std::chrono::nanoseconds refreshCycleDuration, std::chrono::nanoseconds timestamp, PresentationMode mode) = 0;
};

struct RenderTimeSpan
{
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::time_point{std::chrono::nanoseconds::zero()};
    std::chrono::steady_clock::time_point end = std::chrono::steady_clock::time_point{std::chrono::nanoseconds::zero()};
    // Stock prediction can retain a backend-specific safety floor while the
    // gated controller learns from the unclamped start/end span.
    std::chrono::nanoseconds predictionFloor = std::chrono::nanoseconds::zero();

    RenderTimeSpan operator|(const RenderTimeSpan &other) const;
};

enum class DirectScanoutTelemetryReason : uint8_t {
    NotAttempted = 0,
    Accepted,
    ViewHidden,
    NoCandidate,
    NoBuffer,
    NoDmaBufAttributes,
    EarlyChecksFailed,
    FormatUnsupported,
    BufferImportFailed,
    ScanoutDisabled,
    NonPrimaryPlaneDisabled,
    ModesetPending,
    ShadowBufferRequired,
    ColorPipelineUnsupported,
    FractionalSourceRect,
    TransformUnsupported,
};

struct FrameLatencyTelemetry
{
    uint64_t frameSequence = 0;
    std::chrono::steady_clock::time_point frameCreated;
    std::chrono::steady_clock::time_point compositeStart;
    std::chrono::steady_clock::time_point completionCallback;
    DirectScanoutTelemetryReason directScanoutReason = DirectScanoutTelemetryReason::NotAttempted;
    uint32_t directScanoutAttempts = 0;
    uint32_t presentationTests = 0;
    uint32_t presentationFallbacks = 0;
    std::chrono::nanoseconds prePaintDuration = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds layerSetupDuration = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds directScanoutPrepareDuration = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds cpuRenderLayersDuration = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds postPaintDuration = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds presentationTestDuration = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds presentQueueDuration = std::chrono::nanoseconds::zero();
};

class KWIN_EXPORT RenderTimeQuery
{
public:
    virtual ~RenderTimeQuery() = default;
    virtual std::optional<RenderTimeSpan> query() = 0;
};

class KWIN_EXPORT CpuRenderTimeQuery : public RenderTimeQuery
{
public:
    /**
     * marks the start of the query
     */
    explicit CpuRenderTimeQuery();

    void end();

    std::optional<RenderTimeSpan> query() override;

private:
    const std::chrono::steady_clock::time_point m_start;
    std::optional<std::chrono::steady_clock::time_point> m_end;
};

class KWIN_EXPORT OutputFrame
{
public:
    explicit OutputFrame(RenderLoop *loop, std::chrono::nanoseconds refreshDuration);
    ~OutputFrame();

    void presented(std::chrono::nanoseconds timestamp, PresentationMode mode);

    void addFeedback(std::shared_ptr<PresentationFeedback> &&feedback);

    void setContentType(ContentType type);
    std::optional<ContentType> contentType() const;

    void setPresentationMode(PresentationMode mode);
    PresentationMode presentationMode() const;

    void addRenderTimeQuery(std::unique_ptr<RenderTimeQuery> &&query);

    std::chrono::steady_clock::time_point targetPageflipTime() const;
    std::chrono::nanoseconds refreshDuration() const;
    std::chrono::nanoseconds predictedRenderTime() const;

    uint64_t latencyFrameSequence() const;
    void recordCompositeStart(std::chrono::steady_clock::time_point timestamp);
    void recordPrePaint(std::chrono::nanoseconds duration);
    void recordLayerSetup(std::chrono::nanoseconds duration);
    void recordDirectScanoutPreparation(std::chrono::nanoseconds duration);
    void recordCpuRenderLayers(std::chrono::nanoseconds duration);
    void recordPostPaint(std::chrono::nanoseconds duration);
    void recordDirectScanout(DirectScanoutTelemetryReason reason);
    void recordPresentationTest(std::chrono::nanoseconds duration);
    void recordPresentationFallback();
    void recordPresentQueue(std::chrono::nanoseconds duration);
    const FrameLatencyTelemetry &latencyTelemetry() const;

    std::optional<double> brightness() const;
    void setBrightness(double brightness);

    std::optional<double> dimmingFactor() const;
    void setDimmingFactor(double factor);

    std::optional<double> artificialHdrHeadroom() const;
    void setArtificialHdrHeadroom(double edr);

private:
    std::optional<RenderTimeSpan> queryRenderTime() const;

    const QPointer<RenderLoop> m_loop;
    const std::chrono::nanoseconds m_refreshDuration;
    const std::chrono::steady_clock::time_point m_targetPageflipTime;
    const std::chrono::nanoseconds m_predictedRenderTime;
    std::vector<std::shared_ptr<PresentationFeedback>> m_feedbacks;
    std::optional<ContentType> m_contentType;
    PresentationMode m_presentationMode = PresentationMode::VSync;
    std::vector<std::unique_ptr<RenderTimeQuery>> m_renderTimeQueries;
    bool m_presented = false;
    std::optional<double> m_brightness;
    std::optional<double> m_dimmingFactor;
    std::optional<double> m_artificialHdrHeadroom;
    FrameLatencyTelemetry m_latencyTelemetry;
};

/**
 * The RenderBackend class is the base class for all rendering backends.
 */
class KWIN_EXPORT RenderBackend : public QObject
{
    Q_OBJECT

public:
    virtual CompositingType compositingType() const = 0;

    virtual bool checkGraphicsReset();

    virtual QList<OutputLayer *> compatibleOutputLayers(BackendOutput *output) = 0;

    virtual DrmDevice *drmDevice() const;

    virtual bool testImportBuffer(GraphicsBuffer *buffer);
    virtual FormatModifierMap supportedFormats() const;
};

} // namespace KWin
