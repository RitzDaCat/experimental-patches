# KWin source reference

This directory preserves the exact source boundary for the latency experiment.

## Pristine upstream snapshot

`upstream/kwin-6.7.5/` is the complete, unmodified extraction of KDE's
`kwin-6.7.5.tar.xz` release archive. It is not committed;
`scripts/verify_reference_sources.sh` extracts it from the hash-checked archive.
To keep a local copy for browsing:

```bash
bsdtar -xf artifacts/sources/kwin-6.7.5.tar.xz -C reference/upstream/
```

- Source URL: `https://download.kde.org/stable/plasma/6.7.5/kwin-6.7.5.tar.xz`
- SHA-256: `6baa910b732d93c48c90f9c1cc685cc93d0b8de0cdf138c24192c045bc3a48e2`
- Files in archive snapshot: 3,247

The upstream licenses, copyright notices, build system, tests, backends, render
loop, DRM code, input stack, effects, and Wayland implementation are retained
as shipped so design questions can be answered against the exact baseline.

## Patched-source overlay

`patched-overlay/` contains every source file changed after applying patches
`0001` through `0021` in PKGBUILD order. It is intentionally an overlay rather
than a second 55 MB source copy.

Changed or added files:

- `autotests/drm/mockDrmTest.cpp`
- `autotests/test_colorspaces.cpp`
- `src/backends/drm/drm_colorop.cpp`
- `src/backends/drm/drm_colorop.h`
- `src/backends/drm/drm_commit_thread.cpp`
- `src/backends/drm/drm_commit_thread.h`
- `src/backends/drm/drm_egl_layer.cpp`
- `src/backends/drm/drm_egl_layer.h`
- `src/backends/drm/drm_gpu.cpp`
- `src/backends/drm/drm_pipeline.cpp`
- `src/backends/drm/drm_plane.cpp`
- `src/backends/drm/drm_plane.h`
- `src/backends/libinput/connection.cpp`
- `src/backends/libinput/connection.h`
- `src/backends/libinput/events.h`
- `src/compositor.cpp`
- `src/core/colorspace.cpp`
- `src/core/outputlayer.cpp`
- `src/core/outputlayer.h`
- `src/core/renderbackend.cpp`
- `src/core/renderbackend.h`
- `src/core/renderloop.h`
- `src/core/renderloop.cpp`
- `src/core/renderloop_p.h`
- `src/opengl/colormanagement.glsl`
- `src/opengl/glrendertimequery.cpp`
- `src/opengl/glshader.cpp`
- `src/opengl/glshader.h`
- `src/opengl/glshadermanager.cpp`
- `src/opengl/glshadermanager.h`
- `src/scene/itemrenderer_opengl.cpp`
- `src/scene/itemrenderer_opengl.h`
- `src/utils/CMakeLists.txt`
- `src/utils/precisetimer.cpp`
- `src/utils/precisetimer.h`

For an existing upstream file, compare the baseline and experiment directly:

```bash
git diff --no-index \
  reference/upstream/kwin-6.7.5/src/core/renderloop.cpp \
  reference/patched-overlay/src/core/renderloop.cpp
```

`precisetimer.cpp` and `precisetimer.h` are new files introduced by the merged
upstream backport, so they have no KWin 6.7.5 baseline counterpart.

Run `scripts/verify_reference_sources.sh` to independently extract the archive,
reapply all twenty-one patches, and byte-compare both the pristine tree and the
35-file patched overlay.
