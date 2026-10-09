/*
    SPDX-FileCopyrightText: 2020 Vlad Zahorodnii <vlad.zahorodnii@kde.org>

    SPDX-License-Identifier: GPL-2.0-or-later
*/

#pragma once

#include "renderbackend.h"
#include "renderjournal.h"
#include "renderloop.h"
#include "utils/precisetimer.h"

#include <QBasicTimer>

#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <limits>
#include <optional>

namespace KWin
{

class SurfaceItem;
class OutputFrame;

class KWIN_EXPORT RenderLoopPrivate
{
public:
    enum class RepaintTelemetryDecision : uint8_t {
        Immediate = 0,
        ForegroundImmediate,
        CadenceDeferred,
        StockDeferred,
    };

    enum class AdaptiveMarginPath : uint8_t {
        VSync,
        AdaptiveSync,
        Async,
        AdaptiveAsync,
        Count,
    };

    struct AdaptiveMarginState {
        std::chrono::nanoseconds margin = std::chrono::nanoseconds::zero();
        std::chrono::nanoseconds largestWakeLateness = std::chrono::nanoseconds::zero();
        std::chrono::nanoseconds secondLargestWakeLateness = std::chrono::nanoseconds::zero();
        unsigned int windowSampleCount = 0;
        unsigned int externalStallCount = 0;
        bool warmedUp = false;
    };

    struct AdaptiveRenderBudgetState {
        std::chrono::nanoseconds budget = std::chrono::nanoseconds::zero();
        std::chrono::nanoseconds emergencyBudget = std::chrono::nanoseconds::zero();
        std::chrono::nanoseconds largestRenderDuration = std::chrono::nanoseconds::zero();
        std::chrono::nanoseconds secondLargestRenderDuration = std::chrono::nanoseconds::zero();
        unsigned int windowSampleCount = 0;
        unsigned int emergencyFramesLeft = 0;
        bool warmedUp = false;
    };

    static RenderLoopPrivate *get(RenderLoop *loop);
    explicit RenderLoopPrivate(RenderLoop *q, BackendOutput *output);

    void dispatch();

    bool compositeTimerActive() const;
    void startCompositeTimer(std::chrono::nanoseconds deadline, std::chrono::nanoseconds currentTime);
    void stopCompositeTimer();
    void startDelayedVrrTimer(std::chrono::nanoseconds deadline);
    void stopDelayedVrrTimer();
    std::chrono::nanoseconds compositorSchedulingMargin() const;
    static AdaptiveMarginPath adaptiveMarginPath(PresentationMode mode);
    AdaptiveMarginState &adaptiveMarginState(AdaptiveMarginPath path);
    const AdaptiveMarginState &adaptiveMarginState(AdaptiveMarginPath path) const;
    void resetAdaptiveCompositorSchedulingMargins();
    void updateAdaptiveCompositorSchedulingMargin();
    std::chrono::nanoseconds renderPrediction() const;
    AdaptiveRenderBudgetState &adaptiveRenderBudgetState(AdaptiveMarginPath path);
    const AdaptiveRenderBudgetState &adaptiveRenderBudgetState(AdaptiveMarginPath path) const;
    void resetAdaptiveRenderBudgets();
    void updateAdaptiveRenderBudget(AdaptiveMarginPath path, std::chrono::nanoseconds rawDuration, std::chrono::nanoseconds refreshDuration);

    void delayScheduleRepaint();
    void scheduleNextRepaint();
    void scheduleRepaint(std::chrono::nanoseconds lastTargetTimestamp);

    void notifyFrameDropped();
    void notifyFrameCompleted(std::chrono::nanoseconds timestamp, std::optional<RenderTimeSpan> renderTime, PresentationMode mode, OutputFrame *frame);
    void notifyVblank(std::chrono::nanoseconds timestamp);

    RenderLoop *const q;
    BackendOutput *const output;
    std::optional<std::fstream> m_debugOutput;
    uint64_t latencyRowsSinceFlush = 0;
    std::chrono::nanoseconds lastPresentationTimestamp = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds nextPresentationTimestamp = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds desiredWakeTimestamp = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds armedWakeTimestamp = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds actualWakeTimestamp = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds appliedSchedulerMargin = std::chrono::nanoseconds::zero();
    std::array<AdaptiveMarginState, static_cast<std::size_t>(AdaptiveMarginPath::Count)> adaptiveMarginStates;
    std::array<AdaptiveRenderBudgetState, static_cast<std::size_t>(AdaptiveMarginPath::Count)> adaptiveRenderBudgetStates;
    AdaptiveMarginPath scheduledAdaptiveMarginPath = AdaptiveMarginPath::VSync;
    AdaptiveMarginPath lastLoggedAdaptiveMarginPath = AdaptiveMarginPath::Count;
    std::chrono::nanoseconds lastLoggedAdaptiveMargin = std::chrono::nanoseconds::min();
    unsigned int lastLoggedAdaptiveExternalStallCount = std::numeric_limits<unsigned int>::max();
    AdaptiveMarginPath lastLoggedRenderBudgetPath = AdaptiveMarginPath::Count;
    std::chrono::nanoseconds lastLoggedRenderBudget = std::chrono::nanoseconds::min();
    std::chrono::nanoseconds lastLoggedEmergencyRenderBudget = std::chrono::nanoseconds::min();
    uint64_t wakeSampleSequence = 0;
    bool wakeSampleEligible = false;
    bool wakeSampleValid = false;
    bool wakeSampleTrained = false;
    bool wasTripleBuffering = false;
    int doubleBufferingCounter = 0;
    std::unique_ptr<PreciseTimer> compositeTimer;
    std::unique_ptr<PreciseTimer> delayedVrrTimer;
    QBasicTimer legacyCompositeTimer;
    QBasicTimer legacyDelayedVrrTimer;
    RenderJournal renderJournal;
    int refreshRate = 60000;
    int pendingFrameCount = 0;
    bool preparingNewFrame = false;
    int inhibitCount = 0;
    bool pendingReschedule = false;
    RepaintTelemetryDecision lastRepaintDecision = RepaintTelemetryDecision::Immediate;
    std::chrono::nanoseconds lastVrrForegroundCadence = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds lastVrrFallbackDeadline = std::chrono::nanoseconds::zero();
    std::chrono::nanoseconds safetyMargin{0};

    PresentationMode presentationMode = PresentationMode::VSync;
    int maxPendingFrameCount = 1;

};

} // namespace KWin
