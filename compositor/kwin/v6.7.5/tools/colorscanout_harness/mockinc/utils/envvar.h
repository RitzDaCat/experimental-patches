#pragma once
#include <optional>
#include <strings.h>
namespace KWin {
inline std::optional<bool> environmentVariableBoolValue(const char *name)
{
    const char *v = getenv(name);
    if (!v || !*v) {
        return std::nullopt;
    }
    return !(strcasecmp(v, "0") == 0 || strcasecmp(v, "false") == 0);
}
}
