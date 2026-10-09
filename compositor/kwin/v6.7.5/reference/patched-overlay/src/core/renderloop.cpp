/*
    SPDX-FileCopyrightText: 2020 Vlad Zahorodnii <vlad.zahorodnii@kde.org>

    SPDX-License-Identifier: GPL-2.0-or-later
*/

#include "renderloop.h"
#include "backendoutput.h"
#include "options.h"
#include "renderloop_p.h"
#include "scene/surfaceitem.h"
#include "utils/envvar.h"
#include "window.h"
#include "workspace.h"

#include <KConfigGroup>
#include <KConfigWatcher>
#include <KSharedConfig>

#include <QCoreApplication>

#include <atomic>
#include <sys/utsname.h>

using namespace std::chrono_literals;

namespace KWin
{

RenderLoopPrivate *RenderLoopPrivate::get(RenderLoop *loop)
{
    return loop->d.get();
}

static bool experimentKernelAllowed()
{
    QByteArray expectedRelease = qgetenv("KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE");
#ifdef KWIN_LATENCY_BAKED_KERNEL_RELEASE
    // The package bakes the build machine's kernel release in so the gate
    // holds with no environment.d profile; the variable stays as an override
    // (set it to any other string to fail closed to stock behaviour).
    if (expectedRelease.isEmpty()) {
        expectedRelease = KWIN_LATENCY_BAKED_KERNEL_RELEASE;
    }
#endif
    if (expectedRelease.isEmpty()) {
        return false;
    }

    struct utsname systemInfo;
    return uname(&systemInfo) == 0 && expectedRelease == systemInfo.release;
}

static const bool s_experimentKernelAllowed = experimentKernelAllowed();
static const bool s_latencyCapture = s_experimentKernelAllowed && qEnvironmentVariableIntValue("KWIN_LATENCY_CAPTURE") == 1;
static const bool s_printDebugInfo = s_experimentKernelAllowed && (s_latencyCapture || qEnvironmentVariableIntValue("KWIN_LOG_PERFORMANCE_DATA") != 0);
static const uint64_t s_compositorTelemetrySampleDivisor = static_cast<uint64_t>(std::clamp(
    environmentVariableIntValue("KWIN_COMPOSITOR_TELEMETRY_SAMPLE_DIVISOR").value_or(16), 1, 4096));
// Boot-time defaults for the runtime policy below. These stay load-time statics
// on purpose: they are only the value a kwinrc key falls back to when it is
// absent, so every KWIN_* variable already documented keeps working unchanged.
// None of them is read on a frame path.
static const bool s_envExperimentEnabled = environmentVariableIntValue("KWIN_LATENCY_EXPERIMENT").value_or(0) == 1;
static const int s_envSchedulerMarginUs = std::clamp(environmentVariableIntValue("KWIN_COMPOSITOR_SCHEDULING_MARGIN_US").value_or(1000), 0, 10'000);
// 0 = fixed, 1 = shadow (learn but don't apply), 2 = adaptive (default).
static const int s_envSchedulerMarginMode = std::clamp(environmentVariableIntValue("KWIN_ADAPTIVE_COMPOSITOR_MARGIN").value_or(2), 0, 2);
// 0 = stock, 1 = shadow (learn but don't apply), 2 = adaptive (default).
static const int s_envRenderBudgetMode = std::clamp(environmentVariableIntValue("KWIN_ADAPTIVE_RENDER_BUDGET").value_or(2), 0, 2);
// Coalesce non-foreground VRR damage to the active surface's measured cadence.
static const bool s_envVrrRepaintCoalescing = environmentVariableIntValue("KWIN_VRR_REPAINT_COALESCING").value_or(1) == 1;

// The live policy. Every member is constant-initialised, so the object needs no
// dynamic initialisation and cannot be caught out by static init order; it holds
// the *effective* values, so a frame path never has to combine the gate, the
// master switch and a knob itself. Frame paths only relaxed-load. The
// KConfigWatcher callback on the main thread is the sole writer, and the knobs
// are independent, so no ordering between them has to be published.
namespace
{
struct LatencyPolicy
{
    std::atomic<bool> enabled{false};
    std::atomic<int> schedulerMarginMode{0};
    std::atomic<int> renderBudgetMode{0};
    std::atomic<bool> vrrRepaintCoalescing{false};
    std::atomic<int> schedulerMarginUs{1000};
};
}
static LatencyPolicy s_policy;

static int policySchedulerMarginMode()
{
    return s_policy.schedulerMarginMode.load(std::memory_order_relaxed);
}

static int policyRenderBudgetMode()
{
    return s_policy.renderBudgetMode.load(std::memory_order_relaxed);
}

static bool policyVrrRepaintCoalescing()
{
    return s_policy.vrrRepaintCoalescing.load(std::memory_order_relaxed);
}

static std::chrono::nanoseconds policySchedulerMargin()
{
    return std::chrono::microseconds(s_policy.schedulerMarginUs.load(std::memory_order_relaxed));
}

// The exact-kernel gate stays a load-time static and becomes the outer AND
// condition rather than the enable: a tester on a different kernel cannot switch
// the experiment on from kwinrc. "Disabled" means the stock policy values are
// driven onto the same code paths -- the merged-upstream PreciseTimer wakeups
// from patches 0001/0002 keep running, they just carry stock numbers.
static void applyLatencyPolicy(bool enabled, int schedulerMarginMode, int renderBudgetMode, bool vrrRepaintCoalescing, int schedulerMarginUs)
{
    const bool active = s_experimentKernelAllowed && enabled;
    s_policy.enabled.store(active, std::memory_order_relaxed);
    s_policy.schedulerMarginMode.store(active ? std::clamp(schedulerMarginMode, 0, 2) : 0, std::memory_order_relaxed);
    s_policy.renderBudgetMode.store(active ? std::clamp(renderBudgetMode, 0, 2) : 0, std::memory_order_relaxed);
    s_policy.vrrRepaintCoalescing.store(active && vrrRepaintCoalescing, std::memory_order_relaxed);
    s_policy.schedulerMarginUs.store(active ? std::clamp(schedulerMarginUs, 0, 10'000) : 1000, std::memory_order_relaxed);

    // A default-off build makes "I installed it and saw no difference" the most
    // common tester report, so the active policy has to be stated rather than
    // inferred. This runs on policy application only, never on a frame path.
    qCDebug(KWIN_CORE, "Latency experiment policy: active=%d (kernel gate=%d, opt-in=%d), margin mode=%d, budget mode=%d, vrr coalescing=%d, margin=%dus",
            s_policy.enabled.load(std::memory_order_relaxed) ? 1 : 0, s_experimentKernelAllowed ? 1 : 0, enabled ? 1 : 0,
            policySchedulerMarginMode(), policyRenderBudgetMode(), policyVrrRepaintCoalescing() ? 1 : 0,
            s_policy.schedulerMarginUs.load(std::memory_order_relaxed));
}

static void loadLatencyPolicy(const KSharedConfig::Ptr &config)
{
    const KConfigGroup group = config->group(QStringLiteral("LatencyExperiment"));
    applyLatencyPolicy(group.readEntry("Enabled", s_envExperimentEnabled),
                       group.readEntry("SchedulerMarginMode", s_envSchedulerMarginMode),
                       group.readEntry("RenderBudgetMode", s_envRenderBudgetMode),
                       group.readEntry("VrrRepaintCoalescing", s_envVrrRepaintCoalescing),
                       group.readEntry("SchedulerMarginUs", s_envSchedulerMarginUs));
}

// Wired once, from the first RenderLoop construction, which is on the main
// thread and after Application has opened kwinrc. KConfigWatcher reloads the
// config before it emits, so
//   kwriteconfig6 --file kwinrc --group LatencyExperiment --key Enabled true --notify
// lands in the running compositor with no logout and no reconfigure round trip.
static void ensureLatencyPolicyLoaded()
{
    static bool wired = false;
    if (wired) {
        return;
    }
    // Environment defaults first, so a RenderLoop built without an Application
    // (the DRM unit tests) still runs against a defined policy.
    applyLatencyPolicy(s_envExperimentEnabled, s_envSchedulerMarginMode, s_envRenderBudgetMode, s_envVrrRepaintCoalescing, s_envSchedulerMarginUs);
    // Not kwinApp(): that static_casts QCoreApplication::instance() behind a
    // Q_ASSERT the release build compiles out, so in testMockDrm -- a plain
    // QTest application that does construct RenderLoops -- it hands back a
    // bogus Application and reading config() off it segfaults. A checked cast
    // is the difference between "no Application" and "not our Application".
    Application *const application = qobject_cast<Application *>(QCoreApplication::instance());
    if (!application || !application->config()) {
        return;
    }
    wired = true;

    const KSharedConfig::Ptr config = application->config();
    loadLatencyPolicy(config);
    // Deliberately never destroyed. The watcher outlives every RenderLoop, and
    // running its destructor during static destruction would touch a D-Bus
    // connection that QCoreApplication has already torn down.
    auto *watcher = new KConfigWatcher::Ptr(KConfigWatcher::create(config));
    QObject::connect(watcher->data(), &KConfigWatcher::configChanged, watcher->data(), [config](const KConfigGroup &group, const QByteArrayList &) {
        if (group.name() == QLatin1StringView("LatencyExperiment")) {
            loadLatencyPolicy(config);
        }
    });
}

static constexpr unsigned int s_adaptiveMarginWindowSize = 256;
static constexpr unsigned int s_adaptiveExternalStallFallbackCount = 2;
static constexpr unsigned int s_adaptiveRenderBudgetWindowSize = 128;
static constexpr unsigned int s_adaptiveRenderEmergencyFrames = s_adaptiveRenderBudgetWindowSize / 16;

static std::chrono::nanoseconds outputRefreshDuration(int refreshRate)
{
    return std::chrono::nanoseconds(1'000'000'000'000ull / std::max(refreshRate, 1));
}

static std::chrono::nanoseconds adaptiveMarginFloor(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 256, 1ns);
}

static std::chrono::nanoseconds adaptiveMarginGuard(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 2048, 1ns);
}

static std::chrono::nanoseconds adaptiveMarginHysteresis(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 1024, 1ns);
}

static std::chrono::nanoseconds adaptiveMarginCeiling(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 4, 1ns);
}

RenderLoopPrivate::RenderLoopPrivate(RenderLoop *q, BackendOutput *output)
    : q(q)
    , output(output)
{
    ensureLatencyPolicyLoaded();
    resetAdaptiveCompositorSchedulingMargins();
    resetAdaptiveRenderBudgets();
    if (s_experimentKernelAllowed) {
        compositeTimer = std::make_unique<PreciseTimer>();
        QObject::connect(compositeTimer.get(), &PreciseTimer::timeout, q, [this] {
            dispatch();
        });
        // Built whenever the gate passes rather than when coalescing happens to
        // be on at construction: the policy is switchable at runtime now, and a
        // timer that does not exist cannot be armed when it flips on.
        delayedVrrTimer = std::make_unique<PreciseTimer>();
        QObject::connect(delayedVrrTimer.get(), &PreciseTimer::timeout, q, [this] {
            this->q->scheduleRepaint(nullptr, nullptr);
        });
    }
}

static std::chrono::nanoseconds renderBudgetFloor(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 64, 1ns);
}

static std::chrono::nanoseconds renderBudgetGuard(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 1024, 1ns);
}

static std::chrono::nanoseconds renderBudgetHysteresis(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 256, 1ns);
}

static std::chrono::nanoseconds renderBudgetCeiling(std::chrono::nanoseconds refreshDuration)
{
    return refreshDuration * 2;
}

static std::chrono::nanoseconds renderBudgetBootstrap(std::chrono::nanoseconds refreshDuration)
{
    return std::max(refreshDuration / 2, 1ns);
}

RenderLoopPrivate::AdaptiveRenderBudgetState &RenderLoopPrivate::adaptiveRenderBudgetState(AdaptiveMarginPath path)
{
    return adaptiveRenderBudgetStates[static_cast<std::size_t>(path)];
}

const RenderLoopPrivate::AdaptiveRenderBudgetState &RenderLoopPrivate::adaptiveRenderBudgetState(AdaptiveMarginPath path) const
{
    return adaptiveRenderBudgetStates[static_cast<std::size_t>(path)];
}

void RenderLoopPrivate::resetAdaptiveRenderBudgets()
{
    for (auto &state : adaptiveRenderBudgetStates) {
        state = AdaptiveRenderBudgetState{};
    }
}

std::chrono::nanoseconds RenderLoopPrivate::renderPrediction() const
{
    const auto stockPrediction = renderJournal.result();
    const auto &state = adaptiveRenderBudgetState(adaptiveMarginPath(presentationMode));
    if (policyRenderBudgetMode() != 2) {
        return stockPrediction;
    }
    if (!state.warmedUp) {
        return renderBudgetBootstrap(outputRefreshDuration(refreshRate));
    }
    return std::max(state.budget, state.emergencyBudget);
}

void RenderLoopPrivate::updateAdaptiveRenderBudget(AdaptiveMarginPath path, std::chrono::nanoseconds rawDuration, std::chrono::nanoseconds refreshDuration)
{
    if (policyRenderBudgetMode() == 0 || refreshDuration <= 0ns) {
        return;
    }

    auto &state = adaptiveRenderBudgetState(path);

    // A fully direct-scanout frame reports no render duration: queryRenderTime()
    // returns an empty RenderTimeSpan. That is a real observation of near-zero
    // compositor work, not a missing measurement, so it must still age the
    // emergency budget and advance the decay window. Returning early here instead
    // latched renderPrediction() for as long as scanout continued -- one spike
    // then woke the compositor up to two refresh intervals early on every frame,
    // the exact opposite of this feature's purpose.
    if (state.emergencyFramesLeft != 0) {
        state.emergencyFramesLeft--;
        if (state.emergencyFramesLeft == 0) {
            state.emergencyBudget = 0ns;
        }
    }

    const auto floor = renderBudgetFloor(refreshDuration);
    const auto guard = renderBudgetGuard(refreshDuration);
    const auto ceiling = renderBudgetCeiling(refreshDuration);
    const auto targetFor = [floor, guard, ceiling](std::chrono::nanoseconds duration) {
        return std::clamp(duration + guard, floor, ceiling);
    };
    const auto closeWindow = [&] {
        const auto target = targetFor(state.secondLargestRenderDuration);
        if (target > state.budget) {
            state.budget = target;
        } else if (target + renderBudgetHysteresis(refreshDuration) <= state.budget) {
            const auto difference = state.budget - target;
            state.budget = std::max(target, state.budget - std::max(difference / 4, guard));
        }

        state.largestRenderDuration = 0ns;
        state.secondLargestRenderDuration = 0ns;
        state.windowSampleCount = 0;
    };

    if (rawDuration <= 0ns) {
        state.windowSampleCount++;
        if (state.windowSampleCount >= s_adaptiveRenderBudgetWindowSize) {
            closeWindow();
        }
        return;
    }

    const auto boundedDuration = std::min(rawDuration, ceiling);

    state.windowSampleCount++;
    if (boundedDuration >= state.largestRenderDuration) {
        state.secondLargestRenderDuration = state.largestRenderDuration;
        state.largestRenderDuration = boundedDuration;
    } else if (boundedDuration > state.secondLargestRenderDuration) {
        state.secondLargestRenderDuration = boundedDuration;
    }

    const bool wasWarmedUp = state.warmedUp;
    if (!wasWarmedUp) {
        state.budget = targetFor(boundedDuration);
        state.warmedUp = true;
    } else {
        const auto sampleTarget = targetFor(boundedDuration);
        if (sampleTarget > state.budget) {
            state.emergencyBudget = std::max(state.emergencyBudget, sampleTarget);
            state.emergencyFramesLeft = s_adaptiveRenderEmergencyFrames;
        }

        const auto repeatedTailTarget = targetFor(state.secondLargestRenderDuration);
        if (repeatedTailTarget > state.budget) {
            state.budget = repeatedTailTarget;
        }
    }

    if (state.windowSampleCount < s_adaptiveRenderBudgetWindowSize) {
        return;
    }

    closeWindow();
}

bool RenderLoopPrivate::compositeTimerActive() const
{
    return s_experimentKernelAllowed ? compositeTimer->isActive() : legacyCompositeTimer.isActive();
}

void RenderLoopPrivate::startCompositeTimer(std::chrono::nanoseconds deadline, std::chrono::nanoseconds currentTime)
{
    if (s_experimentKernelAllowed) {
        compositeTimer->start(deadline);
    } else {
        legacyCompositeTimer.start(std::max(0ms, std::chrono::duration_cast<std::chrono::milliseconds>(deadline - currentTime)), Qt::PreciseTimer, q);
    }
}

void RenderLoopPrivate::stopCompositeTimer()
{
    if (s_experimentKernelAllowed) {
        compositeTimer->stop();
    } else {
        legacyCompositeTimer.stop();
    }
}

void RenderLoopPrivate::startDelayedVrrTimer(std::chrono::nanoseconds deadline)
{
    // The policy can flip between one arm and the next, so whichever timer is
    // not being used has to be disarmed here as well; otherwise a flip strands a
    // pending wakeup on the timer that armed it and the repaint fires twice.
    if (delayedVrrTimer && policyVrrRepaintCoalescing()) {
        legacyDelayedVrrTimer.stop();
        delayedVrrTimer->start(deadline);
    } else {
        if (delayedVrrTimer && delayedVrrTimer->isActive()) {
            delayedVrrTimer->stop();
        }
        constexpr std::chrono::milliseconds stockDelay = 1'000ms / 30;
        legacyDelayedVrrTimer.start(stockDelay, Qt::PreciseTimer, q);
    }
}

void RenderLoopPrivate::stopDelayedVrrTimer()
{
    if (delayedVrrTimer && delayedVrrTimer->isActive()) {
        delayedVrrTimer->stop();
    }
    legacyDelayedVrrTimer.stop();
}

std::chrono::nanoseconds RenderLoopPrivate::compositorSchedulingMargin() const
{
    return policySchedulerMarginMode() == 2 ? adaptiveMarginState(adaptiveMarginPath(presentationMode)).margin : policySchedulerMargin();
}

RenderLoopPrivate::AdaptiveMarginPath RenderLoopPrivate::adaptiveMarginPath(PresentationMode mode)
{
    switch (mode) {
    case PresentationMode::VSync:
        return AdaptiveMarginPath::VSync;
    case PresentationMode::AdaptiveSync:
        return AdaptiveMarginPath::AdaptiveSync;
    case PresentationMode::Async:
        return AdaptiveMarginPath::Async;
    case PresentationMode::AdaptiveAsync:
        return AdaptiveMarginPath::AdaptiveAsync;
    }
    Q_UNREACHABLE();
}

RenderLoopPrivate::AdaptiveMarginState &RenderLoopPrivate::adaptiveMarginState(AdaptiveMarginPath path)
{
    return adaptiveMarginStates[static_cast<std::size_t>(path)];
}

const RenderLoopPrivate::AdaptiveMarginState &RenderLoopPrivate::adaptiveMarginState(AdaptiveMarginPath path) const
{
    return adaptiveMarginStates[static_cast<std::size_t>(path)];
}

void RenderLoopPrivate::resetAdaptiveCompositorSchedulingMargins()
{
    const auto ceiling = adaptiveMarginCeiling(outputRefreshDuration(refreshRate));
    for (auto &state : adaptiveMarginStates) {
        state = AdaptiveMarginState{};
        state.margin = ceiling;
    }
    wakeSampleEligible = false;
    wakeSampleValid = false;
    wakeSampleTrained = false;
}

void RenderLoopPrivate::updateAdaptiveCompositorSchedulingMargin()
{
    wakeSampleValid = wakeSampleEligible
        && desiredWakeTimestamp != 0ns
        && desiredWakeTimestamp == armedWakeTimestamp
        && actualWakeTimestamp >= armedWakeTimestamp;
    // One armed wake trains the margin at most once. Consuming the eligibility
    // here keeps a second dispatch against the same arm from counting one
    // physical wake twice; scheduleNextRepaint re-arms it for the next wake.
    wakeSampleEligible = false;
    wakeSampleTrained = false;
    if (policySchedulerMarginMode() == 0 || !wakeSampleValid) {
        return;
    }

    auto &state = adaptiveMarginState(scheduledAdaptiveMarginPath);
    const auto wakeLateness = actualWakeTimestamp - armedWakeTimestamp;
    const auto refreshDuration = outputRefreshDuration(refreshRate);
    const auto floor = adaptiveMarginFloor(refreshDuration);
    const auto guard = adaptiveMarginGuard(refreshDuration);
    const auto hysteresis = adaptiveMarginHysteresis(refreshDuration);
    const auto ceiling = adaptiveMarginCeiling(refreshDuration);
    state.windowSampleCount++;
    wakeSampleTrained = true;

    if (wakeLateness > ceiling) {
        state.externalStallCount++;
        // One unrelated scheduler stall is not allowed to poison the margin.
        // A second stall in the same bounded window restores the known-safe
        // configured reserve immediately.
        if (state.externalStallCount >= s_adaptiveExternalStallFallbackCount) {
            state.margin = ceiling;
        }
    } else if (wakeLateness >= state.largestWakeLateness) {
        state.secondLargestWakeLateness = state.largestWakeLateness;
        state.largestWakeLateness = wakeLateness;
    } else if (wakeLateness > state.secondLargestWakeLateness) {
        state.secondLargestWakeLateness = wakeLateness;
    }

    // The second observation is enough to prove this is no longer an isolated
    // spike. Pay that repeated tail immediately instead of waiting for the
    // remainder of the window.
    const auto repeatedTailTarget = std::clamp(state.secondLargestWakeLateness + guard, floor, ceiling);
    if (repeatedTailTarget > state.margin) {
        state.margin = repeatedTailTarget;
    }

    if (state.windowSampleCount < s_adaptiveMarginWindowSize) {
        return;
    }

    const auto target = state.externalStallCount >= s_adaptiveExternalStallFallbackCount
        ? ceiling
        : std::clamp(state.secondLargestWakeLateness + guard, floor, ceiling);

    if (target > state.margin) {
        state.margin = target;
    } else if (target + hysteresis <= state.margin) {
        const auto difference = state.margin - target;
        state.margin = std::max(target, state.margin - std::max(difference / 4, guard));
    }

    state.warmedUp = true;
    state.largestWakeLateness = 0ns;
    state.secondLargestWakeLateness = 0ns;
    state.windowSampleCount = 0;
    state.externalStallCount = 0;
}

static unsigned int adaptiveMarginPathNumber(RenderLoopPrivate::AdaptiveMarginPath path)
{
    return static_cast<unsigned int>(path);
}

void RenderLoopPrivate::scheduleNextRepaint()
{
    if (kwinApp()->isTerminating() || compositeTimerActive() || preparingNewFrame) {
        return;
    }
    scheduleRepaint(nextPresentationTimestamp);
}

void RenderLoopPrivate::scheduleRepaint(std::chrono::nanoseconds lastTargetTimestamp)
{
    pendingReschedule = false;
    const std::chrono::nanoseconds vblankInterval(1'000'000'000'000ull / refreshRate);
    const std::chrono::nanoseconds currentTime(std::chrono::steady_clock::now().time_since_epoch());

    // Estimate when it's a good time to perform the next compositing cycle.
    scheduledAdaptiveMarginPath = adaptiveMarginPath(presentationMode);
    wakeSampleEligible = true;
    appliedSchedulerMargin = compositorSchedulingMargin();
    std::chrono::nanoseconds expectedCompositingTime = std::min(renderPrediction() + safetyMargin + appliedSchedulerMargin, 2 * vblankInterval);

    if (presentationMode == PresentationMode::VSync) {
        // normal presentation: pageflips only happen at vblank
        const uint64_t pageflipsSince = std::max<int64_t>((currentTime - lastPresentationTimestamp) / vblankInterval, 0);
        if (pageflipsSince > 100) {
            // if it's been a while since the last frame, the GPU is likely in a low power state and render time will be increased
            // -> take that into account and start compositing very early
            expectedCompositingTime = std::max(vblankInterval - 1us, expectedCompositingTime);
            wakeSampleEligible = false;
        }
        const uint64_t pageflipsSinceLastToTarget = std::max<int64_t>(std::round((lastTargetTimestamp - lastPresentationTimestamp).count() / double(vblankInterval.count())), 0);
        uint64_t pageflipsInAdvance = std::min<int64_t>(expectedCompositingTime / vblankInterval + 1, maxPendingFrameCount);

        // switching from double to triple buffering causes a frame drop
        // -> apply some amount of hysteresis to avoid switching back and forth constantly
        if (pageflipsInAdvance > 1) {
            // immediately switch to triple buffering when needed
            wasTripleBuffering = true;
            doubleBufferingCounter = 0;
        } else if (wasTripleBuffering) {
            // but wait a bit before switching back to double buffering
            if (doubleBufferingCounter >= 10) {
                wasTripleBuffering = false;
            } else if (expectedCompositingTime >= vblankInterval * 0.95) {
                // also don't switch back if render times are just barely enough for double buffering
                pageflipsInAdvance = 2;
                doubleBufferingCounter = 0;
                expectedCompositingTime = vblankInterval;
            } else {
                doubleBufferingCounter++;
                pageflipsInAdvance = 2;
                expectedCompositingTime = vblankInterval;
            }
        }

        if (compositeTimerActive()) {
            // we already scheduled this frame, but we got a new timestamp
            // which might require starting to composite earlier than we planned
            // It's important here that we do not change the targeted vblank interval,
            // otherwise with a pessimistic compositing time estimation we might
            // unnecessarily drop frames
            const uint32_t intervalsSinceLastTimestamp = std::max<int32_t>(std::round((nextPresentationTimestamp - lastPresentationTimestamp).count() / double(vblankInterval.count())), 0);
            nextPresentationTimestamp = lastPresentationTimestamp + intervalsSinceLastTimestamp * vblankInterval;
        } else {
            nextPresentationTimestamp = lastPresentationTimestamp + std::max(pageflipsSince + pageflipsInAdvance, pageflipsSinceLastToTarget + 1) * vblankInterval;
        }
    } else {
        wasTripleBuffering = false;
        doubleBufferingCounter = 0;
        if (presentationMode == PresentationMode::Async || presentationMode == PresentationMode::AdaptiveAsync) {
            // tearing: pageflips happen ASAP
            nextPresentationTimestamp = currentTime;
        } else {
            // adaptive sync: pageflips happen after one vblank interval
            // TODO read minimum refresh rate from the EDID and take it into account here
            nextPresentationTimestamp = std::max(currentTime, lastPresentationTimestamp + vblankInterval);
        }
    }

    const std::chrono::nanoseconds nextRenderTimestamp = nextPresentationTimestamp - expectedCompositingTime;
    desiredWakeTimestamp = nextRenderTimestamp;
    armedWakeTimestamp = std::max(nextRenderTimestamp, currentTime);
    startCompositeTimer(nextRenderTimestamp, currentTime);
}

void RenderLoopPrivate::delayScheduleRepaint()
{
    pendingReschedule = true;
}

void RenderLoopPrivate::notifyFrameDropped()
{
    Q_ASSERT(pendingFrameCount > 0);
    pendingFrameCount--;

    if (!inhibitCount && pendingReschedule) {
        scheduleNextRepaint();
    }
}

void RenderLoopPrivate::notifyFrameCompleted(std::chrono::nanoseconds timestamp, std::optional<RenderTimeSpan> renderTime, PresentationMode mode, OutputFrame *frame)
{
    const auto completedPath = adaptiveMarginPath(mode);
    const auto rawRenderDuration = renderTime ? std::max(renderTime->end - renderTime->start, 0ns) : 0ns;
    const auto stockRenderDuration = renderTime ? std::max(rawRenderDuration, renderTime->predictionFloor) : 0ns;
    updateAdaptiveRenderBudget(completedPath, rawRenderDuration, frame->refreshDuration());

    if (output && s_printDebugInfo && !m_debugOutput) {
        m_debugOutput = std::fstream(qPrintable("kwin perf statistics " + output->name() + ".csv"), std::ios::out);
        *m_debugOutput << "target pageflip timestamp,pageflip timestamp,render start,render end,safety margin,refresh duration,vrr,tearing,predicted render time,desired wake timestamp,armed wake timestamp,actual wake timestamp,wake lateness,schedule deficit,compositor scheduling margin,adaptive compositor scheduling margin,compositor margin mode,wake sample valid,experiment kernel allowed,adaptive margin path,adaptive window samples,adaptive external stalls,adaptive second peak,adaptive state warmed,wake sample sequence,wake sample trained,telemetry sample divisor,raw render duration,stock render duration,stock render prediction,adaptive render budget,emergency render budget,render budget mode,render budget path,render budget window samples,render budget second peak,render budget warmed,repaint decision,vrr foreground cadence,vrr fallback deadline,direct scanout reason,direct scanout attempts,presentation tests,presentation test duration,presentation fallbacks,present queue duration,frame sequence,frame created timestamp,composite start timestamp,completion callback timestamp,prepaint duration,layer setup duration,direct scanout prepare duration,render layers duration,scene frame and postpaint duration\n";
    }
    if (m_debugOutput) {
        const auto &adaptiveState = adaptiveMarginState(scheduledAdaptiveMarginPath);
        const auto &renderBudgetState = adaptiveRenderBudgetState(completedPath);
        const bool stateChanged = scheduledAdaptiveMarginPath != lastLoggedAdaptiveMarginPath
            || adaptiveState.margin != lastLoggedAdaptiveMargin
            || adaptiveState.externalStallCount != lastLoggedAdaptiveExternalStallCount
            || completedPath != lastLoggedRenderBudgetPath
            || renderBudgetState.budget != lastLoggedRenderBudget
            || renderBudgetState.emergencyBudget != lastLoggedEmergencyRenderBudget;
        const bool periodicSample = s_latencyCapture || wakeSampleSequence == 1 || wakeSampleSequence % s_compositorTelemetrySampleDivisor == 0;
        if (periodicSample || stateChanged) {
            auto times = renderTime.value_or(RenderTimeSpan{});
            const bool vrr = mode == PresentationMode::AdaptiveSync || mode == PresentationMode::AdaptiveAsync;
            const bool tearing = mode == PresentationMode::Async || mode == PresentationMode::AdaptiveAsync;
            const auto wakeLateness = std::max(actualWakeTimestamp - armedWakeTimestamp, 0ns);
            const auto scheduleDeficit = std::max(armedWakeTimestamp - desiredWakeTimestamp, 0ns);
            const auto &frameTelemetry = frame->latencyTelemetry();
            *m_debugOutput << frame->targetPageflipTime().time_since_epoch().count() << "," << timestamp.count() << "," << times.start.time_since_epoch().count() << "," << times.end.time_since_epoch().count()
                           << "," << safetyMargin.count() << "," << frame->refreshDuration().count() << "," << (vrr ? 1 : 0) << "," << (tearing ? 1 : 0) << "," << frame->predictedRenderTime().count()
                           << "," << desiredWakeTimestamp.count() << "," << armedWakeTimestamp.count() << "," << actualWakeTimestamp.count() << "," << wakeLateness.count() << "," << scheduleDeficit.count() << "," << appliedSchedulerMargin.count()
                           << "," << adaptiveState.margin.count() << "," << policySchedulerMarginMode() << "," << (wakeSampleValid ? 1 : 0) << "," << (s_experimentKernelAllowed ? 1 : 0)
                           << "," << adaptiveMarginPathNumber(scheduledAdaptiveMarginPath) << "," << adaptiveState.windowSampleCount << "," << adaptiveState.externalStallCount << "," << adaptiveState.secondLargestWakeLateness.count()
                           << "," << (adaptiveState.warmedUp ? 1 : 0) << "," << wakeSampleSequence << "," << (wakeSampleTrained ? 1 : 0) << "," << s_compositorTelemetrySampleDivisor
                           << "," << rawRenderDuration.count() << "," << stockRenderDuration.count() << "," << renderJournal.result().count() << "," << renderBudgetState.budget.count() << "," << renderBudgetState.emergencyBudget.count()
                           << "," << policyRenderBudgetMode() << "," << adaptiveMarginPathNumber(completedPath) << "," << renderBudgetState.windowSampleCount << "," << renderBudgetState.secondLargestRenderDuration.count() << "," << (renderBudgetState.warmedUp ? 1 : 0)
                           << "," << static_cast<unsigned int>(lastRepaintDecision) << "," << lastVrrForegroundCadence.count() << "," << lastVrrFallbackDeadline.count()
                           << "," << static_cast<unsigned int>(frameTelemetry.directScanoutReason) << "," << frameTelemetry.directScanoutAttempts << "," << frameTelemetry.presentationTests << "," << frameTelemetry.presentationTestDuration.count()
                           << "," << frameTelemetry.presentationFallbacks << "," << frameTelemetry.presentQueueDuration.count()
                           << "," << frameTelemetry.frameSequence << "," << frameTelemetry.frameCreated.time_since_epoch().count() << "," << frameTelemetry.compositeStart.time_since_epoch().count()
                           << "," << frameTelemetry.completionCallback.time_since_epoch().count() << "," << frameTelemetry.prePaintDuration.count() << "," << frameTelemetry.layerSetupDuration.count()
                           << "," << frameTelemetry.directScanoutPrepareDuration.count() << "," << frameTelemetry.cpuRenderLayersDuration.count() << "," << frameTelemetry.postPaintDuration.count() << "\n";
            if (s_latencyCapture && ++latencyRowsSinceFlush == 256) {
                m_debugOutput->flush();
                latencyRowsSinceFlush = 0;
            }
            lastLoggedAdaptiveMargin = adaptiveState.margin;
            lastLoggedAdaptiveMarginPath = scheduledAdaptiveMarginPath;
            lastLoggedAdaptiveExternalStallCount = adaptiveState.externalStallCount;
            lastLoggedRenderBudgetPath = completedPath;
            lastLoggedRenderBudget = renderBudgetState.budget;
            lastLoggedEmergencyRenderBudget = renderBudgetState.emergencyBudget;
        }
    }

    Q_ASSERT(pendingFrameCount > 0);
    pendingFrameCount--;

    notifyVblank(timestamp);

    if (renderTime) {
        renderJournal.add(stockRenderDuration, timestamp);
    }
    if (compositeTimerActive()) {
        // reschedule to match the new timestamp and render time
        scheduleRepaint(lastPresentationTimestamp);
    }
    if (!inhibitCount && pendingReschedule) {
        scheduleNextRepaint();
    }

    Q_EMIT q->framePresented(q, timestamp, mode);
}

void RenderLoopPrivate::notifyVblank(std::chrono::nanoseconds timestamp)
{
    if (lastPresentationTimestamp <= timestamp) {
        lastPresentationTimestamp = timestamp;
    } else {
        qCDebug(KWIN_CORE,
                "Got invalid presentation timestamp: %lld (current %lld)",
                static_cast<long long>(timestamp.count()),
                static_cast<long long>(lastPresentationTimestamp.count()));
        lastPresentationTimestamp = std::chrono::steady_clock::now().time_since_epoch();
    }
}

void RenderLoop::timerEvent(QTimerEvent *event)
{
    if (event->timerId() == d->legacyCompositeTimer.timerId()) {
        d->legacyCompositeTimer.stop();
        d->dispatch();
    } else if (event->timerId() == d->legacyDelayedVrrTimer.timerId()) {
        d->legacyDelayedVrrTimer.stop();
        scheduleRepaint(nullptr, nullptr);
    } else {
        QObject::timerEvent(event);
    }
}

void RenderLoopPrivate::dispatch()
{
    actualWakeTimestamp = std::chrono::steady_clock::now().time_since_epoch();
    wakeSampleSequence++;
    updateAdaptiveCompositorSchedulingMargin();
    Q_EMIT q->frameRequested(q);
}

RenderLoop::RenderLoop(BackendOutput *output)
    : d(std::make_unique<RenderLoopPrivate>(this, output))
{
}

RenderLoop::~RenderLoop()
{
}

void RenderLoop::inhibit()
{
    d->inhibitCount++;

    if (d->inhibitCount == 1) {
        d->stopCompositeTimer();
    }
}

void RenderLoop::uninhibit()
{
    Q_ASSERT(d->inhibitCount > 0);
    d->inhibitCount--;

    if (d->inhibitCount == 0) {
        d->scheduleNextRepaint();
    }
}

void RenderLoop::prepareNewFrame()
{
    d->pendingFrameCount++;
    d->preparingNewFrame = true;
}

void RenderLoop::newFramePrepared()
{
    d->preparingNewFrame = false;
}

int RenderLoop::refreshRate() const
{
    return d->refreshRate;
}

void RenderLoop::setRefreshRate(int refreshRate)
{
    if (d->refreshRate == refreshRate) {
        return;
    }
    d->refreshRate = refreshRate;
    d->resetAdaptiveCompositorSchedulingMargins();
    d->resetAdaptiveRenderBudgets();
    Q_EMIT refreshRateChanged();

    if (d->compositeTimerActive()) {
        d->scheduleRepaint(d->lastPresentationTimestamp);
    }
}

void RenderLoop::setPresentationSafetyMargin(std::chrono::nanoseconds safetyMargin)
{
    d->safetyMargin = safetyMargin;
}

void RenderLoop::scheduleRepaint(Item *item, OutputLayer *outputLayer)
{
    if (s_printDebugInfo) {
        d->lastRepaintDecision = RenderLoopPrivate::RepaintTelemetryDecision::Immediate;
        d->lastVrrForegroundCadence = 0ns;
        d->lastVrrFallbackDeadline = 0ns;
    }
    const bool vrr = d->presentationMode == PresentationMode::AdaptiveSync || d->presentationMode == PresentationMode::AdaptiveAsync;
    const bool tearing = d->presentationMode == PresentationMode::Async || d->presentationMode == PresentationMode::AdaptiveAsync;
    const auto activeFrameTime = (vrr || tearing) && (item || outputLayer) ? activeWindowFrameTimeEstimation() : std::nullopt;
    if (activeFrameTime && d->output) {
        SurfaceItem *const surfaceItem = workspace()->activeWindow()->surfaceItem();
        if (item != surfaceItem && !surfaceItem->isAncestorOf(item)) {
            if (policyVrrRepaintCoalescing()) {
                const auto foregroundCadence = std::max(*activeFrameTime, outputRefreshDuration(d->refreshRate));
                const auto currentTime = std::chrono::steady_clock::now().time_since_epoch();
                const auto foregroundDeadline = std::max(d->lastPresentationTimestamp + foregroundCadence, currentTime);
                if (s_printDebugInfo) {
                    d->lastRepaintDecision = RenderLoopPrivate::RepaintTelemetryDecision::CadenceDeferred;
                    d->lastVrrForegroundCadence = foregroundCadence;
                    d->lastVrrFallbackDeadline = foregroundDeadline;
                }
                d->startDelayedVrrTimer(foregroundDeadline);
            } else {
                if (s_printDebugInfo) {
                    d->lastRepaintDecision = RenderLoopPrivate::RepaintTelemetryDecision::StockDeferred;
                }
                d->startDelayedVrrTimer(0ns);
            }
            return;
        }
        if (s_printDebugInfo) {
            d->lastRepaintDecision = RenderLoopPrivate::RepaintTelemetryDecision::ForegroundImmediate;
            d->lastVrrForegroundCadence = *activeFrameTime;
        }
    }
    d->stopDelayedVrrTimer();
    const int effectiveMaxPendingFrameCount = (vrr || tearing) ? 1 : d->maxPendingFrameCount;
    if (d->pendingFrameCount < effectiveMaxPendingFrameCount && !d->inhibitCount) {
        d->scheduleNextRepaint();
    } else {
        d->delayScheduleRepaint();
    }
}

bool RenderLoop::activeWindowControlsVrrRefreshRate() const
{
    return activeWindowFrameTimeEstimation().has_value();
}

std::optional<std::chrono::nanoseconds> RenderLoop::activeWindowFrameTimeEstimation() const
{
    if (Q_UNLIKELY(!workspace())) {
        return std::nullopt;
    }

    Window *const activeWindow = workspace()->activeWindow();
    LogicalOutput *logical = workspace()->findOutput(d->output);
    if (!logical) {
        return std::nullopt;
    }
    if (!activeWindow
        || !activeWindow->frameGeometry().intersects(logical->geometryF())
        || !activeWindow->surfaceItem()) {
        return std::nullopt;
    }
    const auto frameTime = activeWindow->surfaceItem()->recursiveFrameTimeEstimation();
    constexpr auto activeCadenceLimit = std::chrono::nanoseconds(1'000'000'000) / 30;
    return frameTime && *frameTime <= activeCadenceLimit ? frameTime : std::nullopt;
}

std::chrono::nanoseconds RenderLoop::lastPresentationTimestamp() const
{
    return d->lastPresentationTimestamp;
}

std::chrono::nanoseconds RenderLoop::nextPresentationTimestamp() const
{
    return d->nextPresentationTimestamp;
}

void RenderLoop::setPresentationMode(PresentationMode mode)
{
    if (mode != d->presentationMode) {
        qCDebug(KWIN_CORE) << "Changed presentation mode to" << mode;
    }
    d->presentationMode = mode;
}

void RenderLoop::setMaxPendingFrameCount(uint32_t maxCount)
{
    d->maxPendingFrameCount = maxCount;
}

std::chrono::nanoseconds RenderLoop::predictedRenderTime() const
{
    return d->renderPrediction();
}

} // namespace KWin

#include "moc_renderloop.cpp"
