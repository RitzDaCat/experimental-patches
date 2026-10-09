/*
    KWin - the KDE window manager
    This file is part of the KDE project.

    SPDX-FileCopyrightText: 2023 Xaver Hugl <xaver.hugl@gmail.com>

    SPDX-License-Identifier: GPL-2.0-or-later
*/
#pragma once

#include <QObject>
#include <QThread>
#include <condition_variable>
#include <fstream>
#include <mutex>
#include <optional>
#include <vector>

namespace KWin
{

class DrmGpu;
class DrmCommit;
class DrmAtomicCommit;
class DrmLegacyCommit;

using TimePoint = std::chrono::steady_clock::time_point;

class DrmCommitThread : public QObject
{
    Q_OBJECT

public:
    explicit DrmCommitThread(DrmGpu *gpu, const QString &name);
    ~DrmCommitThread();

    void addCommit(std::unique_ptr<DrmAtomicCommit> &&commit);
    void setPendingCommit(std::unique_ptr<DrmLegacyCommit> &&commit);

    void setModeInfo(uint32_t maximum, std::chrono::nanoseconds vblankTime);
    void pageFlipped(std::chrono::nanoseconds timestamp);
    bool pageflipsPending();
    /**
     * @return how long before the desired presentation timestamp the commit has to be added
     *         in order to get presented at that timestamp
     */
    std::chrono::nanoseconds safetyMargin() const;

private:
    struct PendingCommitTelemetry {
        uint64_t sequence = 0;
        TimePoint target;
        TimePoint queuedAt;
        TimePoint submitStart;
        TimePoint submitEnd;
        std::chrono::nanoseconds queueAge = std::chrono::nanoseconds::zero();
        std::chrono::nanoseconds safetyMargin = std::chrono::nanoseconds::zero();
        std::chrono::nanoseconds baseSafetyMargin = std::chrono::nanoseconds::zero();
        uint64_t readinessRetries = 0;
        uint64_t queueDepth = 0;
        bool vrr = false;
        bool tearing = false;
    };

    void clearDroppedCommits();
    TimePoint estimateNextVblank(TimePoint now) const;
    void optimizeCommits(TimePoint pageflipTarget);
    void submit();
    void handlePing();
    void writeCommitTelemetry(const PendingCommitTelemetry &sample, bool success, std::chrono::nanoseconds pageflipTimestamp, TimePoint callbackTime);

    DrmGpu *const m_gpu;
    std::unique_ptr<DrmCommit> m_committed;
    std::vector<std::unique_ptr<DrmAtomicCommit>> m_commits;
    std::unique_ptr<QThread> m_thread;
    std::mutex m_mutex;
    std::condition_variable m_commitPending;
    std::condition_variable m_pong;
    TimePoint m_lastPageflip;
    TimePoint m_targetPageflipTime;
    TimePoint m_lastCommitTime;
    std::chrono::nanoseconds m_minVblankInterval;
    std::vector<std::unique_ptr<DrmAtomicCommit>> m_commitsToDelete;
    bool m_vrr = false;
    bool m_tearing = false;
    std::chrono::nanoseconds m_safetyMargin{0};
    std::chrono::nanoseconds m_baseSafetyMargin{0};
    std::chrono::nanoseconds m_additionalSafetyMargin = std::chrono::milliseconds(1);
    bool m_ping = false;
    bool m_pageflipTimeoutDetected = false;
    std::optional<std::fstream> m_latencyOutput;
    std::optional<PendingCommitTelemetry> m_pendingCommitTelemetry;
    TimePoint m_oldestQueuedAt;
    uint64_t m_latencySequence = 0;
    uint64_t m_readinessRetries = 0;
    uint64_t m_latencyRowsSinceFlush = 0;
};

}
