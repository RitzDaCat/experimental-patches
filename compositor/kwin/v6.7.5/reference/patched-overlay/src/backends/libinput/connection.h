/*
    KWin - the KDE window manager
    This file is part of the KDE project.

    SPDX-FileCopyrightText: 2014 Martin Gräßlin <mgraesslin@kde.org>

    SPDX-License-Identifier: GPL-2.0-or-later
*/
#pragma once

#include "effect/globals.h"

#include <KSharedConfig>

#include <QList>
#include <QObject>
#include <QPointer>
#include <QRecursiveMutex>
#include <QSize>
#include <QStringList>
#include <array>
#include <chrono>
#include <cstdint>
#include <deque>
#include <fstream>
#include <optional>

class QSocketNotifier;
class QThread;

struct libinput_tablet_tool;

namespace KWin
{

class Session;
class Udev;

namespace LibInput
{

class Event;
class Device;
class Context;
class ConnectionAdaptor;
class TabletTool;

class KWIN_EXPORT Connection : public QObject
{
    Q_OBJECT

public:
    ~Connection() override;

    void setInputConfig(const KSharedConfigPtr &config)
    {
        m_config = config;
    }

    void setup();
    void updateScreens();
    void deactivate();
    void processEvents();

    QList<Device *> devices() const;
    QStringList devicesSysNames() const;

    QStringList ListPointers() const;
    QStringList ListKeyboards() const;
    QStringList ListTouch() const;

    static Connection *create(Session *session);

Q_SIGNALS:
    void deviceAdded(KWin::LibInput::Device *);
    void deviceRemoved(KWin::LibInput::Device *);

    void eventsRead();

private Q_SLOTS:
    void slotKGlobalSettingsNotifyChange(int type, int arg);

private:
    enum class InputTelemetryEventClass : std::size_t {
        PointerMotion,
        PointerButton,
        KeyboardKey,
        Other,
        Count,
    };
    static constexpr std::size_t s_inputTelemetryAgeBucketCount = 16;

    struct InputTelemetryDistribution {
        uint64_t count = 0;
        uint64_t sumNs = 0;
        uint64_t maxNs = 0;
        std::array<uint64_t, s_inputTelemetryAgeBucketCount> buckets{};
    };

    struct InputTelemetryWindow {
        uint64_t producerBatches = 0;
        uint64_t eventsQueued = 0;
        uint64_t motionsQueued = 0;
        uint64_t consumerBatches = 0;
        uint64_t eventsProcessed = 0;
        uint64_t motionsCoalesced = 0;
        uint64_t maxQueueDepth = 0;
        InputTelemetryDistribution producerWait;
        InputTelemetryDistribution producerHold;
        InputTelemetryDistribution consumerWait;
        InputTelemetryDistribution consumerHold;
        std::array<InputTelemetryDistribution, static_cast<std::size_t>(InputTelemetryEventClass::Count)> eventAge{};
    };

    Connection(std::unique_ptr<Context> &&input);
    void handleEvent();
    void recordInputTelemetryDuration(InputTelemetryDistribution &distribution, std::chrono::nanoseconds duration);
    void recordInputTelemetryEvent(const Event *event, std::chrono::nanoseconds drainStart);
    void writeInputTelemetry(const InputTelemetryWindow &window, std::chrono::nanoseconds intervalEnd, std::chrono::nanoseconds intervalDuration);
    void applyDeviceConfig(Device *device);
    void applyScreenToDevice(Device *device);
    void doSetup();
    TabletTool *getOrCreateTool(libinput_tablet_tool *tool);

    std::unique_ptr<QSocketNotifier> m_notifier;
    QRecursiveMutex m_mutex;
    std::deque<std::unique_ptr<Event>> m_eventQueue;
    QList<Device *> m_devices;
    QList<TabletTool *> m_tools;
    KSharedConfigPtr m_config;
    std::unique_ptr<ConnectionAdaptor> m_connectionAdaptor;
    std::unique_ptr<Context> m_input;
    std::unique_ptr<Udev> m_udev;
    bool m_inputTelemetryEnabled = false;
    uint64_t m_inputTelemetrySampleDivisor = 64;
    uint64_t m_inputTelemetryProducerSampleCountdown = 1;
    uint64_t m_inputTelemetryConsumerSampleCountdown = 1;
    uint64_t m_inputTelemetryEventSampleCountdown = 1;
    uint64_t m_inputTelemetryQueuedSamples = 0;
    std::chrono::nanoseconds m_inputTelemetryInterval = std::chrono::seconds(5);
    std::chrono::nanoseconds m_inputTelemetryWindowStart = std::chrono::nanoseconds::zero();
    InputTelemetryWindow m_inputTelemetryWindow;
    std::optional<std::fstream> m_inputTelemetryOutput;
};

}
}
