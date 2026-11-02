// Mock DRM plumbing for the offline direct-scanout color harness.
// Provides exactly the API surface drm_colorop.cpp uses, plus readback of
// everything KWin programs so the harness can simulate hardware faithfully.
#pragma once

#include <xf86drmMode.h>

#include <QByteArray>
#include <QLoggingCategory>
#include <cstdint>
#include <map>
#include <memory>
#include <set>
#include <vector>

Q_DECLARE_LOGGING_CATEGORY(KWIN_DRM)

namespace KWin
{

class DrmGpu;
class DrmAtomicCommit;

// ---------------------------------------------------------------- devices

class DrmDevice
{
public:
    bool isAmdgpu() const { return false; }
    bool isNvidia() const { return true; }
};

class DrmGpu
{
public:
    DrmGpu()
        : m_device(std::make_shared<DrmDevice>())
    {
    }
    DrmDevice *drmDevice() const { return m_device.get(); }

private:
    std::shared_ptr<DrmDevice> m_device;
};

// ---------------------------------------------------------------- blobs

class DrmBlob
{
public:
    static std::shared_ptr<DrmBlob> create(DrmGpu *, const void *data, size_t size)
    {
        auto blob = std::make_shared<DrmBlob>();
        const auto *bytes = static_cast<const uint8_t *>(data);
        blob->data.assign(bytes, bytes + size);
        return blob;
    }
    std::vector<uint8_t> data;
};

// ---------------------------------------------------------------- properties

class DrmObject;

class DrmProperty
{
public:
    DrmProperty(DrmObject *owner, const QByteArray &name)
        : m_owner(owner)
        , m_name(name)
    {
    }
    virtual ~DrmProperty() = default;

    bool isValid() const { return m_valid; }
    uint64_t value() const { return m_value; }
    DrmObject *drmObject() const { return m_owner; }
    QByteArray propertyName() const { return m_name; }

    // harness setup helpers
    void forceValue(uint64_t v)
    {
        m_valid = true;
        m_value = v;
    }

    void update(const struct DrmPropertyList &)
    {
    }

    bool m_valid = false;
    uint64_t m_value = 0;
    DrmObject *m_owner;
    QByteArray m_name;
};

template<typename T>
class DrmEnumProperty : public DrmProperty
{
public:
    using DrmProperty::DrmProperty;

    DrmEnumProperty(DrmObject *owner, const QByteArray &name, std::initializer_list<QByteArray>)
        : DrmProperty(owner, name)
    {
    }

    bool hasEnumForValue(uint64_t v) const { return m_allowed.contains(v); }
    T enumValue() const { return static_cast<T>(m_value); }
    bool hasEnum(T t) const { return m_allowed.contains(static_cast<uint64_t>(t)); }

    void forceAllowed(std::initializer_list<uint64_t> values)
    {
        m_allowed.insert(values.begin(), values.end());
    }

    std::set<uint64_t> m_allowed;
};

struct DrmPropertyList
{
};

class DrmObject
{
public:
    DrmObject(DrmGpu *gpu, uint32_t id, uint32_t)
        : m_gpu(gpu)
        , m_id(id)
    {
    }
    virtual ~DrmObject() = default;

    DrmGpu *gpu() const { return m_gpu; }
    DrmObject *drmObject() { return this; }
    uint32_t objectId() const { return m_id; }

    virtual void disable(DrmAtomicCommit *) {}
    virtual bool updateProperties() { return true; }

protected:
    DrmPropertyList queryProperties() { return {}; }

private:
    DrmGpu *m_gpu;
    uint32_t m_id;
};

// ---------------------------------------------------------------- commits

// Every programmed value lands in a global registry keyed by property
// pointer, so the harness can read back the exact hardware state.
struct CommitEntry
{
    uint64_t value = 0;
    bool hasValue = false;
    std::shared_ptr<DrmBlob> blob;
};

class DrmAtomicCommit
{
public:
    explicit DrmAtomicCommit(DrmGpu *gpu)
        : m_gpu(gpu)
    {
    }

    DrmGpu *gpu() const { return m_gpu; }

    void addProperty(DrmProperty &prop, uint64_t value)
    {
        auto &entry = s_registry[&prop];
        entry.value = value;
        entry.hasValue = true;
    }

    void addBlob(DrmProperty &prop, std::shared_ptr<DrmBlob> blob)
    {
        s_registry[&prop].blob = std::move(blob);
    }

    template<typename T>
    void addEnum(DrmEnumProperty<T> &prop, T value)
    {
        addProperty(prop, static_cast<uint64_t>(value));
    }

    void merge(DrmAtomicCommit *other)
    {
        // all writes already reached the registry; nothing else to do
        (void)other;
    }

    static const CommitEntry *entry(const DrmProperty *prop)
    {
        auto it = s_registry.find(const_cast<DrmProperty *>(prop));
        return it == s_registry.end() ? nullptr : &it->second;
    }

private:
    inline static std::map<const DrmProperty *, CommitEntry> s_registry;
    DrmGpu *m_gpu;
};

}

namespace KWin
{
using ::KWin::CommitEntry;
}
