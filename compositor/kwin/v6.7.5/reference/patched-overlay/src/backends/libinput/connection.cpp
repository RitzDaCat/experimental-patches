/*
    KWin - the KDE window manager
    This file is part of the KDE project.

    SPDX-FileCopyrightText: 2014 Martin Gräßlin <mgraesslin@kde.org>

    SPDX-License-Identifier: GPL-2.0-or-later
*/
#include "connection.h"
#include "context.h"
#include "core/backendoutput.h"
#include "device.h"
#include "events.h"

// TODO: Make it compile also in testing environment
#ifndef KWIN_BUILD_TESTING
#include "core/output.h"
#include "core/outputbackend.h"
#include "main.h"
#include "window.h"
#include "workspace.h"
#endif

#include "core/session.h"
#include "input_event.h"
#include "libinput_logging.h"
#include "utils/realtime.h"
#include "utils/udev.h"

#include <QDBusConnection>
#include <QMutexLocker>
#include <QSocketNotifier>

#include <algorithm>
#include <cmath>
#include <libinput.h>
#include <ranges>
#include <sys/utsname.h>

namespace KWin
{
namespace LibInput
{

static bool inputTelemetryEnabled()
{
    if (qEnvironmentVariableIntValue("KWIN_LATENCY_CAPTURE") != 1
        && qEnvironmentVariableIntValue("KWIN_INPUT_LATENCY_TELEMETRY") == 0) {
        return false;
    }

    const QByteArray expectedRelease = qgetenv("KWIN_COMPOSITOR_EXPERIMENT_KERNEL_RELEASE");
    if (expectedRelease.isEmpty()) {
        return false;
    }

    struct utsname systemInfo;
    return uname(&systemInfo) == 0 && expectedRelease == systemInfo.release;
}

static std::chrono::nanoseconds inputTelemetryInterval()
{
    bool ok = false;
    const int configuredIntervalMs = qEnvironmentVariableIntValue("KWIN_INPUT_LATENCY_TELEMETRY_INTERVAL_MS", &ok);
    return std::chrono::milliseconds(std::clamp(ok ? configuredIntervalMs : 5000, 1000, 60'000));
}

static uint64_t inputTelemetrySampleDivisor()
{
    bool ok = false;
    const int configuredDivisor = qEnvironmentVariableIntValue("KWIN_INPUT_LATENCY_TELEMETRY_SAMPLE_DIVISOR", &ok);
    return static_cast<uint64_t>(std::clamp(ok ? configuredDivisor : 64, 1, 4096));
}

static bool inputTelemetryAlwaysSamples(libinput_event_type type)
{
    return type == LIBINPUT_EVENT_POINTER_BUTTON || type == LIBINPUT_EVENT_KEYBOARD_KEY;
}

static constexpr std::array<std::chrono::nanoseconds, 15> s_inputTelemetryAgeThresholds = {
    std::chrono::microseconds(1),
    std::chrono::microseconds(2),
    std::chrono::microseconds(4),
    std::chrono::microseconds(8),
    std::chrono::microseconds(16),
    std::chrono::microseconds(32),
    std::chrono::microseconds(64),
    std::chrono::microseconds(125),
    std::chrono::microseconds(250),
    std::chrono::microseconds(500),
    std::chrono::microseconds(1000),
    std::chrono::microseconds(2000),
    std::chrono::microseconds(4000),
    std::chrono::microseconds(8000),
    std::chrono::microseconds(16000),
};

static constexpr std::array<const char *, 4> s_inputTelemetryEventClassNames = {
    "motion",
    "button",
    "key",
    "other",
};

static constexpr std::array<const char *, 16> s_inputTelemetryAgeBucketNames = {
    "le_1us",
    "le_2us",
    "le_4us",
    "le_8us",
    "le_16us",
    "le_32us",
    "le_64us",
    "le_125us",
    "le_250us",
    "le_500us",
    "le_1000us",
    "le_2000us",
    "le_4000us",
    "le_8000us",
    "le_16000us",
    "gt_16000us",
};

static uint64_t nanosecondsCount(std::chrono::nanoseconds duration)
{
    return static_cast<uint64_t>(std::max(duration, std::chrono::nanoseconds::zero()).count());
}

static std::size_t inputTelemetryAgeBucket(std::chrono::nanoseconds age)
{
    const auto it = std::ranges::lower_bound(s_inputTelemetryAgeThresholds, age);
    return static_cast<std::size_t>(std::distance(s_inputTelemetryAgeThresholds.begin(), it));
}

class ConnectionAdaptor : public QObject
{
    Q_OBJECT
    Q_CLASSINFO("D-Bus Interface", "org.kde.KWin.InputDeviceManager")
    Q_PROPERTY(QStringList devicesSysNames READ devicesSysNames CONSTANT)

private:
    Connection *m_con;

public:
    ConnectionAdaptor(Connection *con)
        : QObject(con)
        , m_con(con)
    {
        connect(con, &Connection::deviceAdded, this, [this](LibInput::Device *inputDevice) {
            Q_EMIT deviceAdded(inputDevice->sysName());
        });
        connect(con, &Connection::deviceRemoved, this, [this](LibInput::Device *inputDevice) {
            Q_EMIT deviceRemoved(inputDevice->sysName());
        });

        QDBusConnection::sessionBus().registerObject(QStringLiteral("/org/kde/KWin/InputDevice"),
                                                     QStringLiteral("org.kde.KWin.InputDeviceManager"),
                                                     this,
                                                     QDBusConnection::ExportAllProperties | QDBusConnection::ExportAllSignals | QDBusConnection::ExportScriptableContents);
    }

    ~ConnectionAdaptor() override
    {
        QDBusConnection::sessionBus().unregisterObject(QStringLiteral("/org/kde/KWin/InputDeviceManager"));
    }

    QStringList devicesSysNames()
    {
        return m_con->devicesSysNames();
    }

    Q_SCRIPTABLE QStringList ListPointers() const
    {
        return m_con->ListPointers();
    }
    Q_SCRIPTABLE QStringList ListKeyboards() const
    {
        return m_con->ListKeyboards();
    }
    Q_SCRIPTABLE QStringList ListTouch() const
    {
        return m_con->ListTouch();
    }

Q_SIGNALS:
    void deviceAdded(QString sysName);
    void deviceRemoved(QString sysName);
};

Connection *Connection::create(Session *session)
{
    std::unique_ptr<Udev> udev = std::make_unique<Udev>();
    if (!udev->isValid()) {
        qCWarning(KWIN_LIBINPUT) << "Failed to initialize udev";
        return nullptr;
    }
    std::unique_ptr<Context> context = std::make_unique<Context>(session, std::move(udev));
    if (!context->isValid()) {
        qCWarning(KWIN_LIBINPUT) << "Failed to create context from udev";
        return nullptr;
    }
    if (!context->initialize()) {
        qCWarning(KWIN_LIBINPUT) << "Failed to initialize context";
        return nullptr;
    }
    return new Connection(std::move(context));
}

Connection::Connection(std::unique_ptr<Context> &&input)
    : m_notifier(nullptr)
    , m_connectionAdaptor(std::make_unique<ConnectionAdaptor>(this))
    , m_input(std::move(input))
    , m_inputTelemetryEnabled(inputTelemetryEnabled())
    , m_inputTelemetrySampleDivisor(inputTelemetrySampleDivisor())
    , m_inputTelemetryInterval(inputTelemetryInterval())
{
    Q_ASSERT(m_input);
    if (m_inputTelemetryEnabled) {
        m_inputTelemetryWindowStart = std::chrono::steady_clock::now().time_since_epoch();
    }
    // need to connect to KGlobalSettings as the mouse KCM does not emit a dedicated signal
    QDBusConnection::sessionBus().connect(QString(), QStringLiteral("/KGlobalSettings"), QStringLiteral("org.kde.KGlobalSettings"),
                                          QStringLiteral("notifyChange"), this, SLOT(slotKGlobalSettingsNotifyChange(int, int)));
}

Connection::~Connection()
{
    m_eventQueue.clear();
    qDeleteAll(m_devices);
    qDeleteAll(m_tools);
}

void Connection::setup()
{
    QMetaObject::invokeMethod(this, &Connection::doSetup, Qt::QueuedConnection);
}

void Connection::doSetup()
{
    Q_ASSERT(!m_notifier);

    gainRealTime();

    m_notifier = std::make_unique<QSocketNotifier>(m_input->fileDescriptor(), QSocketNotifier::Read);
    connect(m_notifier.get(), &QSocketNotifier::activated, this, &Connection::handleEvent);

    connect(m_input->session(), &Session::activeChanged, this, [this](bool active) {
        if (active) {
            if (!m_input->isSuspended()) {
                return;
            }
            m_input->resume();
        } else {
            deactivate();
        }
    });
    handleEvent();
}

void Connection::deactivate()
{
    if (m_input->isSuspended()) {
        return;
    }
    m_input->suspend();
    handleEvent();
}

void Connection::handleEvent()
{
    const bool sampleProducerTiming = m_inputTelemetryEnabled && --m_inputTelemetryProducerSampleCountdown == 0;
    if (sampleProducerTiming) {
        m_inputTelemetryProducerSampleCountdown = m_inputTelemetrySampleDivisor;
    }
    const auto waitStart = sampleProducerTiming ? std::chrono::steady_clock::now().time_since_epoch() : std::chrono::nanoseconds::zero();
    QMutexLocker locker(&m_mutex);
    const auto lockAcquired = sampleProducerTiming ? std::chrono::steady_clock::now().time_since_epoch() : std::chrono::nanoseconds::zero();
    const bool wasEmpty = m_eventQueue.empty();
    uint64_t eventsQueued = 0;
    do {
        m_input->dispatch();
        std::unique_ptr<Event> event = m_input->event();
        if (!event) {
            break;
        }
        if (m_inputTelemetryEnabled) {
            eventsQueued++;
            const bool periodicSample = --m_inputTelemetryEventSampleCountdown == 0;
            if (periodicSample) {
                m_inputTelemetryEventSampleCountdown = m_inputTelemetrySampleDivisor;
            }
            if (periodicSample || inputTelemetryAlwaysSamples(event->type())) {
                event->setInputTelemetryQueuedTimestamp(std::chrono::steady_clock::now().time_since_epoch());
                m_inputTelemetryQueuedSamples++;
            }
            if (event->type() == LIBINPUT_EVENT_POINTER_MOTION || event->type() == LIBINPUT_EVENT_POINTER_MOTION_ABSOLUTE) {
                m_inputTelemetryWindow.motionsQueued++;
            }
        }
        m_eventQueue.push_back(std::move(event));
    } while (true);
    if (wasEmpty && !m_eventQueue.empty()) {
        Q_EMIT eventsRead();
    }
    if (m_inputTelemetryEnabled) {
        m_inputTelemetryWindow.producerBatches++;
        m_inputTelemetryWindow.eventsQueued += eventsQueued;
        m_inputTelemetryWindow.maxQueueDepth = std::max<uint64_t>(m_inputTelemetryWindow.maxQueueDepth, m_eventQueue.size());
        if (sampleProducerTiming) {
            const auto lockReleased = std::chrono::steady_clock::now().time_since_epoch();
            recordInputTelemetryDuration(m_inputTelemetryWindow.producerWait, lockAcquired - waitStart);
            recordInputTelemetryDuration(m_inputTelemetryWindow.producerHold, lockReleased - lockAcquired);
        }
    }
}

#ifndef KWIN_BUILD_TESTING
QPointF devicePointToGlobalPosition(const QPointF &devicePos, const BackendOutput *output)
{
    QPointF pos = devicePos;
    // TODO: Do we need to handle the flipped cases differently?
    switch (output->transform().kind()) {
    case OutputTransform::Normal:
    case OutputTransform::FlipX:
        break;
    case OutputTransform::Rotate90:
    case OutputTransform::FlipX90:
        pos = QPointF(output->modeSize().height() - devicePos.y(), devicePos.x());
        break;
    case OutputTransform::Rotate180:
    case OutputTransform::FlipX180:
        pos = QPointF(output->modeSize().width() - devicePos.x(),
                      output->modeSize().height() - devicePos.y());
        break;
    case OutputTransform::Rotate270:
    case OutputTransform::FlipX270:
        pos = QPointF(devicePos.y(), output->modeSize().width() - devicePos.x());
        break;
    default:
        Q_UNREACHABLE();
    }
    pos -= output->deviceOffset();
    pos = pos / output->scale();

    auto logicalOutput = workspace()->findOutput(output);
    if (!logicalOutput) {
        qWarning() << "Could not find logical output for " << output;
        return {};
    }
    const QRectF geo = logicalOutput->geometryF();
    pos += geo.topLeft();
    return QPointF(std::clamp(pos.x(), geo.x(), geo.x() + geo.width() - 1),
                   std::clamp(pos.y(), geo.y(), geo.y() + geo.height() - 1));
}
#endif

static QPointF tabletToolPosition(TabletToolEvent *event)
{
#ifndef KWIN_BUILD_TESTING
    if (event->device()->isMapToWorkspace()) {
        return workspace()->geometry().topLeft() + event->transformedPosition(workspace()->geometry().size());
    } else {
        BackendOutput *backendOutput = event->device()->output();
        if (backendOutput) {
            return devicePointToGlobalPosition(event->transformedPosition(backendOutput->modeSize()), backendOutput);
        }
        BackendOutput *output = workspace()->activeOutput()->backendOutput();
        return devicePointToGlobalPosition(event->transformedPosition(output->modeSize()), output);
    }
#else
    return QPointF();
#endif
}

TabletTool *Connection::getOrCreateTool(libinput_tablet_tool *handle)
{
    for (TabletTool *tool : std::as_const(m_tools)) {
        if (tool->handle() == handle) {
            return tool;
        }
    }

    auto tool = new TabletTool(handle);
    tool->moveToThread(thread());
    m_tools.append(tool);

    return tool;
}

void Connection::processEvents()
{
    const bool sampleConsumerTiming = m_inputTelemetryEnabled && --m_inputTelemetryConsumerSampleCountdown == 0;
    if (sampleConsumerTiming) {
        m_inputTelemetryConsumerSampleCountdown = m_inputTelemetrySampleDivisor;
    }
    const auto waitStart = sampleConsumerTiming ? std::chrono::steady_clock::now().time_since_epoch() : std::chrono::nanoseconds::zero();
    QMutexLocker locker(&m_mutex);
    auto lockAcquired = sampleConsumerTiming ? std::chrono::steady_clock::now().time_since_epoch() : std::chrono::nanoseconds::zero();
    if (m_inputTelemetryEnabled) {
        m_inputTelemetryWindow.consumerBatches++;
        m_inputTelemetryWindow.eventsProcessed += m_eventQueue.size();
        m_inputTelemetryWindow.maxQueueDepth = std::max<uint64_t>(m_inputTelemetryWindow.maxQueueDepth, m_eventQueue.size());
        if (m_inputTelemetryQueuedSamples != 0) {
            if (lockAcquired == std::chrono::nanoseconds::zero()) {
                lockAcquired = std::chrono::steady_clock::now().time_since_epoch();
            }
            for (const auto &event : m_eventQueue) {
                recordInputTelemetryEvent(event.get(), lockAcquired);
            }
            m_inputTelemetryQueuedSamples = 0;
        }
    }
    while (m_eventQueue.size() != 0) {
        std::unique_ptr<Event> event = std::move(m_eventQueue.front());
        m_eventQueue.pop_front();
        switch (event->type()) {
        case LIBINPUT_EVENT_DEVICE_ADDED: {
            auto device = new Device(event->nativeDevice());
            device->moveToThread(thread());
            m_devices << device;

            applyDeviceConfig(device);
            applyScreenToDevice(device);

            connect(device, &Device::outputNameChanged, this, [this, device] {
                // If the output name changes from something to empty we need to
                // re-run the assignment heuristic so that an output is assigned
                if (device->outputName().isEmpty()) {
                    applyScreenToDevice(device);
                }
            });

            Q_EMIT deviceAdded(device);
            break;
        }
        case LIBINPUT_EVENT_DEVICE_REMOVED: {
            auto it = std::ranges::find_if(std::as_const(m_devices), [&event](Device *d) {
                return event->device() == d;
            });
            if (it == m_devices.cend()) {
                // we don't know this device
                break;
            }
            auto device = *it;
            m_devices.erase(it);
            Q_EMIT deviceRemoved(device);
            device->deleteLater();
            break;
        }
        case LIBINPUT_EVENT_KEYBOARD_KEY: {
            KeyEvent *ke = static_cast<KeyEvent *>(event.get());
            const int seatKeyCount = libinput_event_keyboard_get_seat_key_count(*ke);
            const int keyState = libinput_event_keyboard_get_key_state(*ke);
            if ((keyState == LIBINPUT_KEY_STATE_PRESSED && seatKeyCount != 1) || (keyState == LIBINPUT_KEY_STATE_RELEASED && seatKeyCount != 0)) {
                break;
            }
            Q_EMIT ke->device()->keyChanged(ke->key(), ke->state(), ke->time(), ke->device());
            break;
        }
        case LIBINPUT_EVENT_POINTER_SCROLL_WHEEL: {
            const PointerEvent *pointerEvent = static_cast<PointerEvent *>(event.get());
            const auto axes = pointerEvent->axis();
            for (const PointerAxis &axis : axes) {
                Q_EMIT pointerEvent->device()->pointerAxisChanged(axis,
                                                                  pointerEvent->scrollValue(axis),
                                                                  pointerEvent->scrollValueV120(axis),
                                                                  PointerAxisSource::Wheel,
                                                                  pointerEvent->device()->isNaturalScroll(),
                                                                  pointerEvent->time(),
                                                                  pointerEvent->device());
            }
            Q_EMIT pointerEvent->device()->pointerFrame(pointerEvent->device());
            break;
        }
        case LIBINPUT_EVENT_POINTER_SCROLL_FINGER: {
            const PointerEvent *pointerEvent = static_cast<PointerEvent *>(event.get());
            const auto axes = pointerEvent->axis();
            for (const PointerAxis &axis : axes) {
                Q_EMIT pointerEvent->device()->pointerAxisChanged(axis,
                                                                  pointerEvent->scrollValue(axis),
                                                                  0,
                                                                  PointerAxisSource::Finger,
                                                                  pointerEvent->device()->isNaturalScroll(),
                                                                  pointerEvent->time(),
                                                                  pointerEvent->device());
            }
            Q_EMIT pointerEvent->device()->pointerFrame(pointerEvent->device());
            break;
        }
        case LIBINPUT_EVENT_POINTER_SCROLL_CONTINUOUS: {
            const PointerEvent *pointerEvent = static_cast<PointerEvent *>(event.get());
            const auto axes = pointerEvent->axis();
            for (const PointerAxis &axis : axes) {
                Q_EMIT pointerEvent->device()->pointerAxisChanged(axis,
                                                                  pointerEvent->scrollValue(axis),
                                                                  0,
                                                                  PointerAxisSource::Continuous,
                                                                  pointerEvent->device()->isNaturalScroll(),
                                                                  pointerEvent->time(),
                                                                  pointerEvent->device());
            }
            Q_EMIT pointerEvent->device()->pointerFrame(pointerEvent->device());
            break;
        }
        case LIBINPUT_EVENT_POINTER_BUTTON: {
            PointerEvent *pe = static_cast<PointerEvent *>(event.get());
            const int seatButtonCount = libinput_event_pointer_get_seat_button_count(*pe);
            const int buttonState = libinput_event_pointer_get_button_state(*pe);
            if ((buttonState == LIBINPUT_BUTTON_STATE_PRESSED && seatButtonCount != 1) || (buttonState == LIBINPUT_BUTTON_STATE_RELEASED && seatButtonCount != 0)) {
                break;
            }
            Q_EMIT pe->device()->pointerButtonChanged(pe->button(), pe->buttonState(), pe->time(), pe->device());
            Q_EMIT pe->device()->pointerFrame(pe->device());
            break;
        }
        case LIBINPUT_EVENT_POINTER_MOTION: {
            PointerEvent *pe = static_cast<PointerEvent *>(event.get());
            auto delta = pe->delta();
            auto deltaNonAccel = pe->deltaUnaccelerated();
            auto latestTime = pe->time();
            auto it = m_eventQueue.begin();
            while (it != m_eventQueue.end()) {
                if ((*it)->type() == LIBINPUT_EVENT_POINTER_MOTION) {
                    if (m_inputTelemetryEnabled) {
                        m_inputTelemetryWindow.motionsCoalesced++;
                    }
                    std::unique_ptr<PointerEvent> p{static_cast<PointerEvent *>(it->release())};
                    delta += p->delta();
                    deltaNonAccel += p->deltaUnaccelerated();
                    latestTime = p->time();
                    it = m_eventQueue.erase(it);
                } else {
                    break;
                }
            }
            Q_EMIT pe->device()->pointerMotion(delta, deltaNonAccel, latestTime, pe->device());
            Q_EMIT pe->device()->pointerFrame(pe->device());
            break;
        }
        case LIBINPUT_EVENT_POINTER_MOTION_ABSOLUTE: {
            PointerEvent *pe = static_cast<PointerEvent *>(event.get());
            if (workspace()) {
                Q_EMIT pe->device()->pointerMotionAbsolute(pe->absolutePos(workspace()->geometry().size()), pe->time(), pe->device());
                Q_EMIT pe->device()->pointerFrame(pe->device());
            }
            break;
        }
        case LIBINPUT_EVENT_TOUCH_DOWN: {
#ifndef KWIN_BUILD_TESTING
            TouchEvent *te = static_cast<TouchEvent *>(event.get());
            const auto *output = te->device()->output();
            if (!output) {
                qCWarning(KWIN_LIBINPUT) << "Touch down received for device with no output assigned";
                break;
            }
            const QPointF globalPos = devicePointToGlobalPosition(te->absolutePos(output->modeSize()), output);
            Q_EMIT te->device()->touchDown(te->id(), globalPos, te->time(), te->device());
            break;
#endif
        }
        case LIBINPUT_EVENT_TOUCH_UP: {
            TouchEvent *te = static_cast<TouchEvent *>(event.get());
            const auto *output = te->device()->output();
            if (!output) {
                break;
            }
            Q_EMIT te->device()->touchUp(te->id(), te->time(), te->device());
            break;
        }
        case LIBINPUT_EVENT_TOUCH_MOTION: {
#ifndef KWIN_BUILD_TESTING
            TouchEvent *te = static_cast<TouchEvent *>(event.get());
            const auto *output = te->device()->output();
            if (!output) {
                break;
            }
            const QPointF globalPos = devicePointToGlobalPosition(te->absolutePos(output->modeSize()), output);
            Q_EMIT te->device()->touchMotion(te->id(), globalPos, te->time(), te->device());
            break;
#endif
        }
        case LIBINPUT_EVENT_TOUCH_CANCEL: {
            Q_EMIT event->device()->touchCanceled(event->device());
            break;
        }
        case LIBINPUT_EVENT_TOUCH_FRAME: {
            Q_EMIT event->device()->touchFrame(event->device());
            break;
        }
        case LIBINPUT_EVENT_GESTURE_PINCH_BEGIN: {
            PinchGestureEvent *pe = static_cast<PinchGestureEvent *>(event.get());
            Q_EMIT pe->device()->pinchGestureBegin(pe->fingerCount(), pe->time(), pe->device());
            break;
        }
        case LIBINPUT_EVENT_GESTURE_PINCH_UPDATE: {
            PinchGestureEvent *pe = static_cast<PinchGestureEvent *>(event.get());
            Q_EMIT pe->device()->pinchGestureUpdate(pe->scale(), pe->angleDelta(), pe->delta(), pe->time(), pe->device());
            break;
        }
        case LIBINPUT_EVENT_GESTURE_PINCH_END: {
            PinchGestureEvent *pe = static_cast<PinchGestureEvent *>(event.get());
            if (pe->isCancelled()) {
                Q_EMIT pe->device()->pinchGestureCancelled(pe->time(), pe->device());
            } else {
                Q_EMIT pe->device()->pinchGestureEnd(pe->time(), pe->device());
            }
            break;
        }
        case LIBINPUT_EVENT_GESTURE_SWIPE_BEGIN: {
            SwipeGestureEvent *se = static_cast<SwipeGestureEvent *>(event.get());
            Q_EMIT se->device()->swipeGestureBegin(se->fingerCount(), se->time(), se->device());
            break;
        }
        case LIBINPUT_EVENT_GESTURE_SWIPE_UPDATE: {
            SwipeGestureEvent *se = static_cast<SwipeGestureEvent *>(event.get());
            Q_EMIT se->device()->swipeGestureUpdate(se->delta(), se->time(), se->device());
            break;
        }
        case LIBINPUT_EVENT_GESTURE_SWIPE_END: {
            SwipeGestureEvent *se = static_cast<SwipeGestureEvent *>(event.get());
            if (se->isCancelled()) {
                Q_EMIT se->device()->swipeGestureCancelled(se->time(), se->device());
            } else {
                Q_EMIT se->device()->swipeGestureEnd(se->time(), se->device());
            }
            break;
        }
        case LIBINPUT_EVENT_GESTURE_HOLD_BEGIN: {
            HoldGestureEvent *he = static_cast<HoldGestureEvent *>(event.get());
            Q_EMIT he->device()->holdGestureBegin(he->fingerCount(), he->time(), he->device());
            break;
        }
        case LIBINPUT_EVENT_GESTURE_HOLD_END: {
            HoldGestureEvent *he = static_cast<HoldGestureEvent *>(event.get());
            if (he->isCancelled()) {
                Q_EMIT he->device()->holdGestureCancelled(he->time(), he->device());
            } else {
                Q_EMIT he->device()->holdGestureEnd(he->time(), he->device());
            }
            break;
        }
        case LIBINPUT_EVENT_SWITCH_TOGGLE: {
            SwitchEvent *se = static_cast<SwitchEvent *>(event.get());
            Q_EMIT se->device()->switchToggle(se->state(), se->time(), se->device());
            break;
        }
        case LIBINPUT_EVENT_TABLET_TOOL_AXIS: {
            auto *tte = static_cast<TabletToolEvent *>(event.get());
            if (libinput_tablet_tool_config_pressure_range_is_available(tte->tool())) {
                tte->device()->setSupportsPressureRange(true);
                libinput_tablet_tool_config_pressure_range_set(tte->tool(), tte->device()->pressureRangeMin(), tte->device()->pressureRangeMax());
            }

            if (event->device()->tabletToolIsRelative()) {
                Q_EMIT event->device()->tabletToolAxisEventRelative(tte->delta(),
                                                                    tte->device()->pressureCurve().valueForProgress(tte->pressure()),
                                                                    tte->xTilt(),
                                                                    tte->yTilt(),
                                                                    tte->rotation(),
                                                                    tte->distance(),
                                                                    tte->isTipDown(),
                                                                    tte->sliderPosition(),
                                                                    getOrCreateTool(tte->tool()),
                                                                    tte->time(),
                                                                    tte->device());
            } else {
                Q_EMIT event->device()->tabletToolAxisEvent(tabletToolPosition(tte),
                                                            tte->device()->pressureCurve().valueForProgress(tte->pressure()),
                                                            tte->xTilt(),
                                                            tte->yTilt(),
                                                            tte->rotation(),
                                                            tte->distance(),
                                                            tte->isTipDown(),
                                                            tte->sliderPosition(),
                                                            getOrCreateTool(tte->tool()),
                                                            tte->time(),
                                                            tte->device());
            }
            break;
        }
        case LIBINPUT_EVENT_TABLET_TOOL_PROXIMITY: {
            auto *tte = static_cast<TabletToolEvent *>(event.get());
            if (libinput_tablet_tool_config_pressure_range_is_available(tte->tool())) {
                tte->device()->setSupportsPressureRange(true);
                libinput_tablet_tool_config_pressure_range_set(tte->tool(), tte->device()->pressureRangeMin(), tte->device()->pressureRangeMax());
            }
            Q_EMIT event->device()->tabletToolProximityEvent(tabletToolPosition(tte),
                                                             tte->xTilt(),
                                                             tte->yTilt(),
                                                             tte->rotation(),
                                                             tte->distance(),
                                                             tte->isNearby(),
                                                             tte->sliderPosition(),
                                                             getOrCreateTool(tte->tool()),
                                                             tte->time(),
                                                             tte->device());
            break;
        }
        case LIBINPUT_EVENT_TABLET_TOOL_TIP: {
            auto *tte = static_cast<TabletToolEvent *>(event.get());
            if (libinput_tablet_tool_config_pressure_range_is_available(tte->tool())) {
                tte->device()->setSupportsPressureRange(true);
                libinput_tablet_tool_config_pressure_range_set(tte->tool(), tte->device()->pressureRangeMin(), tte->device()->pressureRangeMax());
            }
            Q_EMIT event->device()->tabletToolTipEvent(tabletToolPosition(tte),
                                                       tte->device()->pressureCurve().valueForProgress(tte->pressure()),
                                                       tte->xTilt(),
                                                       tte->yTilt(),
                                                       tte->rotation(),
                                                       tte->distance(),
                                                       tte->isTipDown(),
                                                       tte->sliderPosition(),
                                                       getOrCreateTool(tte->tool()),
                                                       tte->time(),
                                                       tte->device());
            break;
        }
        case LIBINPUT_EVENT_TABLET_TOOL_BUTTON: {
            auto *tabletEvent = static_cast<TabletToolButtonEvent *>(event.get());
            Q_EMIT event->device()->tabletToolButtonEvent(tabletEvent->buttonId(),
                                                          tabletEvent->isButtonPressed(),
                                                          getOrCreateTool(tabletEvent->tool()), tabletEvent->time(), tabletEvent->device());
            break;
        }
        case LIBINPUT_EVENT_TABLET_PAD_BUTTON: {
            auto *tabletEvent = static_cast<TabletPadButtonEvent *>(event.get());
            Q_EMIT event->device()->tabletPadButtonEvent(tabletEvent->buttonId(),
                                                         tabletEvent->isButtonPressed(),
                                                         tabletEvent->group(),
                                                         tabletEvent->mode(),
                                                         tabletEvent->isModeSwitch(),
                                                         tabletEvent->time(), tabletEvent->device());
            break;
        }
        case LIBINPUT_EVENT_TABLET_PAD_RING: {
            auto *tabletEvent = static_cast<TabletPadRingEvent *>(event.get());
            Q_EMIT event->device()->tabletPadRingEvent(tabletEvent->number(),
                                                       tabletEvent->position(),
                                                       tabletEvent->source() == LIBINPUT_TABLET_PAD_RING_SOURCE_FINGER,
                                                       tabletEvent->group(),
                                                       tabletEvent->mode(),
                                                       tabletEvent->time(), tabletEvent->device());
            break;
        }
        case LIBINPUT_EVENT_TABLET_PAD_STRIP: {
            auto *tabletEvent = static_cast<TabletPadStripEvent *>(event.get());
            Q_EMIT event->device()->tabletPadStripEvent(tabletEvent->number(),
                                                        tabletEvent->position(),
                                                        tabletEvent->source() == LIBINPUT_TABLET_PAD_STRIP_SOURCE_FINGER,
                                                        tabletEvent->group(),
                                                        tabletEvent->mode(),
                                                        tabletEvent->time(), tabletEvent->device());
            break;
        }
        case LIBINPUT_EVENT_TABLET_PAD_DIAL: {
            auto *tabletEvent = static_cast<TabletPadDialEvent *>(event.get());
            Q_EMIT event->device()->tabletPadDialEvent(tabletEvent->number(), tabletEvent->delta(), tabletEvent->group(), tabletEvent->time(), tabletEvent->device());
            break;
        }
        default:
            // nothing
            break;
        }
    }

    std::optional<InputTelemetryWindow> completedWindow;
    std::chrono::nanoseconds completedWindowDuration = std::chrono::nanoseconds::zero();
    const auto lockReleased = sampleConsumerTiming ? std::chrono::steady_clock::now().time_since_epoch() : std::chrono::nanoseconds::zero();
    if (sampleConsumerTiming) {
        recordInputTelemetryDuration(m_inputTelemetryWindow.consumerWait, lockAcquired - waitStart);
        recordInputTelemetryDuration(m_inputTelemetryWindow.consumerHold, lockReleased - lockAcquired);

        completedWindowDuration = lockReleased - m_inputTelemetryWindowStart;
        if (completedWindowDuration >= m_inputTelemetryInterval) {
            completedWindow = m_inputTelemetryWindow;
            m_inputTelemetryWindow = InputTelemetryWindow{};
            m_inputTelemetryWindowStart = lockReleased;
        }
    }
    locker.unlock();
    if (completedWindow) {
        writeInputTelemetry(*completedWindow, lockReleased, completedWindowDuration);
    }
}

void Connection::recordInputTelemetryDuration(InputTelemetryDistribution &distribution, std::chrono::nanoseconds duration)
{
    const auto boundedDuration = std::max(duration, std::chrono::nanoseconds::zero());
    const uint64_t durationNs = nanosecondsCount(boundedDuration);
    distribution.count++;
    distribution.sumNs += durationNs;
    distribution.maxNs = std::max(distribution.maxNs, durationNs);
    distribution.buckets[inputTelemetryAgeBucket(boundedDuration)]++;
}

void Connection::recordInputTelemetryEvent(const Event *event, std::chrono::nanoseconds drainStart)
{
    InputTelemetryEventClass eventClass = InputTelemetryEventClass::Other;
    switch (event->type()) {
    case LIBINPUT_EVENT_POINTER_MOTION:
    case LIBINPUT_EVENT_POINTER_MOTION_ABSOLUTE:
        eventClass = InputTelemetryEventClass::PointerMotion;
        break;
    case LIBINPUT_EVENT_POINTER_BUTTON:
        eventClass = InputTelemetryEventClass::PointerButton;
        break;
    case LIBINPUT_EVENT_KEYBOARD_KEY:
        eventClass = InputTelemetryEventClass::KeyboardKey;
        break;
    default:
        break;
    }

    const auto queuedTimestamp = event->inputTelemetryQueuedTimestamp();
    if (queuedTimestamp == std::chrono::nanoseconds::zero()) {
        return;
    }
    const auto age = std::max(drainStart - queuedTimestamp, std::chrono::nanoseconds::zero());
    recordInputTelemetryDuration(m_inputTelemetryWindow.eventAge[static_cast<std::size_t>(eventClass)], age);
}

void Connection::writeInputTelemetry(const InputTelemetryWindow &window, std::chrono::nanoseconds intervalEnd, std::chrono::nanoseconds intervalDuration)
{
    if (!m_inputTelemetryOutput) {
        m_inputTelemetryOutput.emplace("kwin input latency.csv", std::ios::out);
        *m_inputTelemetryOutput << "schema_version,sample_divisor,interval_end_ns,interval_duration_ns,producer_batches,events_queued,motions_queued,consumer_batches,events_processed,motions_coalesced,max_queue_depth";
        for (const char *distribution : {"producer_wait", "producer_hold", "consumer_wait", "consumer_hold"}) {
            *m_inputTelemetryOutput << "," << distribution << "_count," << distribution << "_sum_ns," << distribution << "_max_ns";
            for (const char *bucket : s_inputTelemetryAgeBucketNames) {
                *m_inputTelemetryOutput << "," << distribution << "_" << bucket;
            }
        }
        for (const char *eventClass : s_inputTelemetryEventClassNames) {
            *m_inputTelemetryOutput << "," << eventClass << "_count," << eventClass << "_age_sum_ns," << eventClass << "_age_max_ns";
            for (const char *bucket : s_inputTelemetryAgeBucketNames) {
                *m_inputTelemetryOutput << "," << eventClass << "_age_" << bucket;
            }
        }
        *m_inputTelemetryOutput << "\n";
    }

    *m_inputTelemetryOutput << 2 << "," << m_inputTelemetrySampleDivisor << "," << intervalEnd.count() << "," << intervalDuration.count()
                            << "," << window.producerBatches << "," << window.eventsQueued << "," << window.motionsQueued
                            << "," << window.consumerBatches << "," << window.eventsProcessed
                            << "," << window.motionsCoalesced << "," << window.maxQueueDepth;
    for (const auto *distribution : {&window.producerWait, &window.producerHold, &window.consumerWait, &window.consumerHold}) {
        *m_inputTelemetryOutput << "," << distribution->count << "," << distribution->sumNs << "," << distribution->maxNs;
        for (const uint64_t bucketCount : distribution->buckets) {
            *m_inputTelemetryOutput << "," << bucketCount;
        }
    }
    for (const auto &eventAge : window.eventAge) {
        *m_inputTelemetryOutput << "," << eventAge.count << "," << eventAge.sumNs << "," << eventAge.maxNs;
        for (const uint64_t bucketCount : eventAge.buckets) {
            *m_inputTelemetryOutput << "," << bucketCount;
        }
    }
    *m_inputTelemetryOutput << "\n";
    // Capture tools read this file while KWin is still running. Flush the
    // userspace stream once per completed window so the bounded trace sees the
    // current interval. This is outside m_mutex and capture-only.
    m_inputTelemetryOutput->flush();
}

void Connection::updateScreens()
{
    QMutexLocker locker(&m_mutex);
    for (auto device : std::as_const(m_devices)) {
        applyScreenToDevice(device);
    }
}

void Connection::applyScreenToDevice(Device *device)
{
#ifndef KWIN_BUILD_TESTING
    QMutexLocker locker(&m_mutex);
    if (!device->isTouch() && !device->isTabletTool()) {
        return;
    }

    BackendOutput *deviceOutput = nullptr;
    const QList<BackendOutput *> outputs = kwinApp()->outputBackend()->outputs();

    // let's try to find a screen for it
    if (!device->outputUuid().isEmpty()) {
        // use the UUID if possible, which is more stable than the output name
        const auto it = std::ranges::find_if(outputs, [device](BackendOutput *output) {
            return output->uuid() == device->outputUuid();
        });
        deviceOutput = it == outputs.end() ? nullptr : *it;
    }
    if (!deviceOutput && !device->outputName().isEmpty()) {
        // we have an output name, try to find a screen with matching name
        for (BackendOutput *output : outputs) {
            if (output->name() == device->outputName()) {
                deviceOutput = output;
                break;
            }
        }
    }
    if (!deviceOutput && device->isTouch()) {
        // do we have an internal screen?
        BackendOutput *internalOutput = nullptr;
        for (BackendOutput *output : outputs) {
            if (output->isInternal()) {
                internalOutput = output;
                break;
            }
        }
        auto testScreenMatches = [device](const BackendOutput *output) {
            const auto &size = device->size();
            const auto &screenSize = output->physicalSize();
            return std::round(size.width()) == std::round(screenSize.width())
                && std::round(size.height()) == std::round(screenSize.height());
        };
        if (internalOutput && testScreenMatches(internalOutput)) {
            deviceOutput = internalOutput;
        }
        // let's compare all screens for size
        for (BackendOutput *output : outputs) {
            if (testScreenMatches(output)) {
                deviceOutput = output;
                break;
            }
        }
        if (!deviceOutput) {
            // still not found
            if (internalOutput) {
                // we have an internal id, so let's use that
                deviceOutput = internalOutput;
            } else if (outputs.size()) {
                // just take first screen, we have no clue
                deviceOutput = outputs.front();
            }
        }
    }

    if (deviceOutput) {
        device->setOutput(deviceOutput);
    }

    // TODO: this is currently non-functional even on DRM. Needs orientation() override there.
    device->setOrientation(Qt::PrimaryOrientation);
#endif
}

void Connection::applyDeviceConfig(Device *device)
{
    KConfigGroup defaults = m_config->group(QStringLiteral("Libinput")).group(QStringLiteral("Defaults"));
    if (defaults.isValid()) {
        if (device->isAlphaNumericKeyboard() && defaults.hasGroup(QStringLiteral("Keyboard"))) {
            defaults = defaults.group(QStringLiteral("Keyboard"));
        } else if (device->isTouchpad() && defaults.hasGroup(QStringLiteral("Touchpad"))) {
            // A Touchpad is a Pointer, so we need to check for it before Pointer.
            defaults = defaults.group(QStringLiteral("Touchpad"));
        } else if (device->isPointer() && defaults.hasGroup(QStringLiteral("Pointer"))) {
            defaults = defaults.group(QStringLiteral("Pointer"));
        }

        device->setDefaultConfig(defaults);
    }

    // pass configuration to Device
    device->setConfig(m_config->group(QStringLiteral("Libinput")).group(QString::number(device->vendor())).group(QString::number(device->product())).group(device->name()));
    device->loadConfiguration();
}

void Connection::slotKGlobalSettingsNotifyChange(int type, int arg)
{
    if (type == 3 /**SettingsChanged**/ && arg == 0 /** SETTINGS_MOUSE */) {
        m_config->reparseConfiguration();
        for (auto it = m_devices.constBegin(), end = m_devices.constEnd(); it != end; ++it) {
            if ((*it)->isPointer()) {
                applyDeviceConfig(*it);
            }
        }
    }
}

QList<Device *> Connection::devices() const
{
    return m_devices;
}

QStringList Connection::devicesSysNames() const
{
    QStringList sl;
    for (Device *d : std::as_const(m_devices)) {
        sl.append(d->sysName());
    }
    return sl;
}

QStringList Connection::ListPointers() const
{
    return m_devices
        | std::views::filter(&Device::isPointer)
        | std::views::transform(&Device::sysName)
        | std::ranges::to<QStringList>();
}

QStringList Connection::ListKeyboards() const
{
    return m_devices
        | std::views::filter(&Device::isKeyboard)
        | std::views::transform(&Device::sysName)
        | std::ranges::to<QStringList>();
}

QStringList Connection::ListTouch() const
{
    return m_devices
        | std::views::filter(&Device::isTouch)
        | std::views::transform(&Device::sysName)
        | std::ranges::to<QStringList>();
}

}
}

#include "connection.moc"

#include "moc_connection.cpp"
