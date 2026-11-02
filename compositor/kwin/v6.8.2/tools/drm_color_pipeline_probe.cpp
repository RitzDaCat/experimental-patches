// SPDX-License-Identifier: MIT
// Read-only DRM plane color-pipeline state and capability probe.

#include <xf86drm.h>
#include <xf86drmMode.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <filesystem>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <unordered_set>
#include <unistd.h>
#include <vector>

namespace
{

template<typename T, void (*FreeFn)(T *)>
using DrmPtr = std::unique_ptr<T, decltype(FreeFn)>;

struct LutComponent32
{
    uint32_t red;
    uint32_t green;
    uint32_t blue;
    uint32_t reserved;
};

struct Options
{
    std::string device = "/dev/dri/card1";
    std::optional<std::filesystem::path> blobDirectory;
};

const char *enumName(const drmModePropertyRes *property, uint64_t value)
{
    for (int i = 0; i < property->count_enums; ++i) {
        if (property->enums[i].value == value) {
            return property->enums[i].name;
        }
    }
    return nullptr;
}

std::string sanitize(std::string value)
{
    for (char &character : value) {
        if (!(character >= 'a' && character <= 'z')
            && !(character >= 'A' && character <= 'Z')
            && !(character >= '0' && character <= '9')
            && character != '-' && character != '_') {
            character = '_';
        }
    }
    return value;
}

double fixedS31_32ToDouble(uint64_t raw)
{
    constexpr uint64_t sign = uint64_t{1} << 63;
    const double magnitude = static_cast<double>(raw & ~sign) / static_cast<double>(uint64_t{1} << 32);
    return raw & sign ? -magnitude : magnitude;
}

void printHexPrefix(std::span<const uint8_t> data, unsigned depth)
{
    constexpr size_t maximum = 32;
    std::printf("%*shex-prefix=", depth * 2, "");
    for (size_t index = 0; index < std::min(data.size(), maximum); ++index) {
        std::printf("%02x", data[index]);
    }
    if (data.size() > maximum) {
        std::printf("...");
    }
    std::printf("\n");
}

void decodeMatrix(std::span<const uint8_t> bytes, unsigned depth)
{
    if (bytes.size() != 9 * sizeof(uint64_t) && bytes.size() != 12 * sizeof(uint64_t)) {
        return;
    }
    const auto *values = reinterpret_cast<const uint64_t *>(bytes.data());
    const size_t columns = bytes.size() == 9 * sizeof(uint64_t) ? 3 : 4;
    std::printf("%*sdecoded-s31.32-matrix:\n", depth * 2, "");
    for (size_t row = 0; row < 3; ++row) {
        std::printf("%*s", (depth + 1) * 2, "");
        for (size_t column = 0; column < columns; ++column) {
            std::printf("%+.12f%s", fixedS31_32ToDouble(values[row * columns + column]),
                        column + 1 == columns ? "" : " ");
        }
        std::printf("\n");
    }
}

void decodeLut32(std::span<const uint8_t> bytes, unsigned depth)
{
    if (bytes.empty() || bytes.size() % sizeof(LutComponent32) != 0) {
        return;
    }
    const auto values = std::span(
        reinterpret_cast<const LutComponent32 *>(bytes.data()),
        bytes.size() / sizeof(LutComponent32));
    const std::array<size_t, 7> requested = {
        0,
        values.size() / 16,
        values.size() / 4,
        values.size() / 2,
        values.size() * 3 / 4,
        values.size() * 15 / 16,
        values.size() - 1,
    };
    const bool equalChannels = std::ranges::all_of(values, [](const LutComponent32 &value) {
        return value.red == value.green && value.green == value.blue;
    });
    std::printf("%*slut32-entries=%zu equal-rgb=%s\n", depth * 2, "", values.size(), equalChannels ? "yes" : "no");
    size_t previous = values.size();
    for (const size_t requestedIndex : requested) {
        const size_t index = std::min(requestedIndex, values.size() - 1);
        if (index == previous) {
            continue;
        }
        previous = index;
        const auto &value = values[index];
        std::printf("%*ssample[%zu]=%u,%u,%u\n", (depth + 1) * 2, "", index,
                    value.red, value.green, value.blue);
    }
}

void writeBlob(const Options &options, uint32_t planeId, uint64_t pipelineId,
               uint32_t objectId, const char *propertyName, uint32_t blobId,
               std::span<const uint8_t> bytes)
{
    if (!options.blobDirectory) {
        return;
    }
    std::filesystem::create_directories(*options.blobDirectory);
    const std::string filename = "plane-" + std::to_string(planeId)
        + "-pipeline-" + std::to_string(pipelineId)
        + "-colorop-" + std::to_string(objectId)
        + "-" + sanitize(propertyName)
        + "-blob-" + std::to_string(blobId) + ".bin";
    const auto destination = *options.blobDirectory / filename;
    FILE *output = std::fopen(destination.c_str(), "wb");
    if (!output) {
        std::fprintf(stderr, "write %s failed: %s\n", destination.c_str(), std::strerror(errno));
        return;
    }
    if (!bytes.empty() && std::fwrite(bytes.data(), 1, bytes.size(), output) != bytes.size()) {
        std::fprintf(stderr, "short write for %s\n", destination.c_str());
    }
    std::fclose(output);
}

void dumpBlob(int fd, const Options &options, uint32_t planeId, uint64_t pipelineId,
              uint32_t objectId, const char *propertyName, uint32_t blobId,
              const std::string &operationType, unsigned depth)
{
    DrmPtr<drmModePropertyBlobRes, drmModeFreePropertyBlob> blob(
        drmModeGetPropertyBlob(fd, blobId),
        drmModeFreePropertyBlob);
    if (!blob) {
        std::printf("%*sblob-query-failed=%s\n", depth * 2, "", std::strerror(errno));
        return;
    }
    const auto bytes = std::span(
        static_cast<const uint8_t *>(blob->data),
        static_cast<size_t>(blob->length));
    std::printf("%*sblob-id=%u bytes=%u\n", depth * 2, "", blob->id, blob->length);
    printHexPrefix(bytes, depth + 1);
    if (operationType == "3x4 Matrix") {
        decodeMatrix(bytes, depth + 1);
    } else if (operationType == "1D LUT") {
        decodeLut32(bytes, depth + 1);
    }
    writeBlob(options, planeId, pipelineId, objectId, propertyName, blobId, bytes);
}

void dumpPropertyFlags(const drmModePropertyRes *property)
{
    std::printf(" flags=");
    bool first = true;
    auto append = [&first](const char *name) {
        std::printf("%s%s", first ? "" : "|", name);
        first = false;
    };
    if (property->flags & DRM_MODE_PROP_IMMUTABLE) {
        append("immutable");
    }
    if (property->flags & DRM_MODE_PROP_RANGE) {
        append("range");
    }
    if (property->flags & DRM_MODE_PROP_SIGNED_RANGE) {
        append("signed-range");
    }
    if (property->flags & DRM_MODE_PROP_ENUM) {
        append("enum");
    }
    if (property->flags & DRM_MODE_PROP_BITMASK) {
        append("bitmask");
    }
    if (property->flags & DRM_MODE_PROP_BLOB) {
        append("blob");
    }
    if (first) {
        std::printf("none");
    }
}

void dumpColorOp(int fd, const Options &options, uint32_t planeId, uint64_t pipelineId,
                 uint32_t objectId, unsigned depth, std::unordered_set<uint32_t> &visited)
{
    if (objectId == 0) {
        std::printf("%*snext: bypass/end\n", depth * 2, "");
        return;
    }
    if (!visited.insert(objectId).second) {
        std::printf("%*scolorop %u: cycle detected\n", depth * 2, "", objectId);
        return;
    }

    DrmPtr<drmModeObjectProperties, drmModeFreeObjectProperties> properties(
        drmModeObjectGetProperties(fd, objectId, DRM_MODE_OBJECT_ANY),
        drmModeFreeObjectProperties);
    if (!properties) {
        std::printf("%*scolorop %u: query failed: %s\n", depth * 2, "", objectId, std::strerror(errno));
        return;
    }

    std::string operationType = "unknown";
    uint32_t next = 0;
    for (uint32_t i = 0; i < properties->count_props; ++i) {
        DrmPtr<drmModePropertyRes, drmModeFreeProperty> property(
            drmModeGetProperty(fd, properties->props[i]),
            drmModeFreeProperty);
        if (!property) {
            continue;
        }
        const uint64_t value = properties->prop_values[i];
        if (std::strcmp(property->name, "TYPE") == 0) {
            if (const char *name = enumName(property.get(), value)) {
                operationType = name;
            }
        } else if (std::strcmp(property->name, "NEXT") == 0) {
            next = static_cast<uint32_t>(value);
        }
    }

    std::printf("%*scolorop %u type=%s\n", depth * 2, "", objectId, operationType.c_str());
    for (uint32_t i = 0; i < properties->count_props; ++i) {
        DrmPtr<drmModePropertyRes, drmModeFreeProperty> property(
            drmModeGetProperty(fd, properties->props[i]),
            drmModeFreeProperty);
        if (!property) {
            continue;
        }
        const uint64_t value = properties->prop_values[i];
        const char *name = enumName(property.get(), value);
        std::printf("%*s%s=%llu", (depth + 1) * 2, "", property->name,
                    static_cast<unsigned long long>(value));
        if (name) {
            std::printf(" (%s)", name);
        }
        dumpPropertyFlags(property.get());
        std::printf("\n");
        if (property->count_values > 0 && !(property->flags & DRM_MODE_PROP_BLOB)) {
            std::printf("%*sallowed-values:", (depth + 2) * 2, "");
            for (int valueIndex = 0; valueIndex < property->count_values; ++valueIndex) {
                std::printf(" %llu", static_cast<unsigned long long>(property->values[valueIndex]));
            }
            std::printf("\n");
        }
        if (property->count_enums > 1 && std::strcmp(property->name, "TYPE") != 0) {
            std::printf("%*savailable:", (depth + 2) * 2, "");
            for (int enumIndex = 0; enumIndex < property->count_enums; ++enumIndex) {
                std::printf(" %llu=%s",
                            static_cast<unsigned long long>(property->enums[enumIndex].value),
                            property->enums[enumIndex].name);
            }
            std::printf("\n");
        }
        if ((property->flags & DRM_MODE_PROP_BLOB) && value != 0) {
            dumpBlob(fd, options, planeId, pipelineId, objectId, property->name,
                     static_cast<uint32_t>(value), operationType, depth + 2);
        }
    }
    dumpColorOp(fd, options, planeId, pipelineId, next, depth + 1, visited);
}

int setCapability(int fd, uint64_t capability, const char *name)
{
    errno = 0;
    const int result = drmSetClientCap(fd, capability, 1);
    std::printf("client-cap %-22s: %s", name, result == 0 ? "enabled" : "failed");
    if (result != 0) {
        std::printf(" (%s)", std::strerror(errno));
    }
    std::printf("\n");
    return result;
}

Options parseOptions(int argc, char **argv)
{
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--device" && index + 1 < argc) {
            options.device = argv[++index];
        } else if (argument == "--blob-dir" && index + 1 < argc) {
            options.blobDirectory = argv[++index];
        } else if (!argument.starts_with("-")) {
            options.device = argument;
        } else {
            std::fprintf(stderr, "usage: %s [--device PATH] [--blob-dir DIRECTORY]\n", argv[0]);
            std::exit(64);
        }
    }
    return options;
}

} // namespace

int main(int argc, char **argv)
{
    const Options options = parseOptions(argc, argv);
    const int fd = open(options.device.c_str(), O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        std::fprintf(stderr, "open %s failed: %s\n", options.device.c_str(), std::strerror(errno));
        return 1;
    }

    std::printf("device: %s\n", options.device.c_str());
    if (options.blobDirectory) {
        std::printf("blob-directory: %s\n", options.blobDirectory->c_str());
    }
    if (setCapability(fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, "universal-planes") != 0
        || setCapability(fd, DRM_CLIENT_CAP_ATOMIC, "atomic") != 0
        || setCapability(fd, DRM_CLIENT_CAP_PLANE_COLOR_PIPELINE, "plane-color-pipeline") != 0) {
        close(fd);
        return 2;
    }

    DrmPtr<drmModePlaneRes, drmModeFreePlaneResources> planes(
        drmModeGetPlaneResources(fd),
        drmModeFreePlaneResources);
    if (!planes) {
        std::fprintf(stderr, "plane resource query failed: %s\n", std::strerror(errno));
        close(fd);
        return 3;
    }

    unsigned pipelineCount = 0;
    unsigned activePipelineCount = 0;
    for (uint32_t planeIndex = 0; planeIndex < planes->count_planes; ++planeIndex) {
        const uint32_t planeId = planes->planes[planeIndex];
        DrmPtr<drmModePlane, drmModeFreePlane> plane(drmModeGetPlane(fd, planeId), drmModeFreePlane);
        DrmPtr<drmModeObjectProperties, drmModeFreeObjectProperties> properties(
            drmModeObjectGetProperties(fd, planeId, DRM_MODE_OBJECT_PLANE),
            drmModeFreeObjectProperties);
        if (!plane || !properties) {
            continue;
        }

        std::string planeType = "unknown";
        uint64_t activePipeline = 0;
        drmModePropertyRes *pipelineProperty = nullptr;
        for (uint32_t i = 0; i < properties->count_props; ++i) {
            DrmPtr<drmModePropertyRes, drmModeFreeProperty> property(
                drmModeGetProperty(fd, properties->props[i]),
                drmModeFreeProperty);
            if (!property) {
                continue;
            }
            if (std::strcmp(property->name, "type") == 0) {
                if (const char *name = enumName(property.get(), properties->prop_values[i])) {
                    planeType = name;
                }
            }
            if (std::strcmp(property->name, "COLOR_PIPELINE") == 0) {
                activePipeline = properties->prop_values[i];
                pipelineProperty = property.release();
            }
        }

        std::printf("\nplane %u type=%s crtc=%u fb=%u possible_crtcs=0x%x\n",
                    planeId, planeType.c_str(), plane->crtc_id, plane->fb_id, plane->possible_crtcs);
        if (!pipelineProperty) {
            std::printf("  COLOR_PIPELINE: unavailable\n");
            continue;
        }

        DrmPtr<drmModePropertyRes, drmModeFreeProperty> pipeline(pipelineProperty, drmModeFreeProperty);
        const char *activePipelineName = enumName(pipeline.get(), activePipeline);
        std::printf("  COLOR_PIPELINE: current=%llu (%s), %d choices\n",
                    static_cast<unsigned long long>(activePipeline),
                    activePipelineName ? activePipelineName : "unknown",
                    pipeline->count_enums);
        if (activePipeline != 0) {
            ++activePipelineCount;
        }
        for (int i = 0; i < pipeline->count_enums; ++i) {
            const uint64_t value = pipeline->enums[i].value;
            std::printf("  choice %llu (%s)%s\n",
                        static_cast<unsigned long long>(value),
                        pipeline->enums[i].name,
                        value == activePipeline ? " [ACTIVE]" : "");
            if (value == 0) {
                continue;
            }
            ++pipelineCount;
            std::unordered_set<uint32_t> visited;
            dumpColorOp(fd, options, planeId, value, static_cast<uint32_t>(value), 2, visited);
        }
    }

    std::printf("\nnon-bypass plane pipeline choices: %u\n", pipelineCount);
    std::printf("planes with an active non-bypass pipeline: %u\n", activePipelineCount);
    close(fd);
    return pipelineCount == 0 ? 4 : 0;
}
