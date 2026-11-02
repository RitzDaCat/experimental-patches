#!/usr/bin/env python3
"""Apply patch 0021 (selectable mandatory CSC PQ scale) edits to a
drm_colorop.cpp/.h pair that already has upstream 6.7.4 + patches 0016 and
0017 applied. Used to keep reference/harness/kwin and the patched overlay
in sync with patches/0021-selectable-mandatory-csc-pq-scale.patch."""

import sys
from pathlib import Path

cpp = Path(sys.argv[1])
hdr = Path(sys.argv[2])

s = cpp.read_text()

# forward declaration: the member helper below is defined before the
# file-local static it calls
anchor = "namespace KWin\n{\n"
decl = "namespace KWin\n{\n\nstatic double mandatoryCscPqScale();\n"
assert anchor in s
s = s.replace(anchor, decl, 1)

old = '''static std::optional<std::pair<TransferFunction::Type, bool>> pickSupportedFunction(DrmEnumProperty<Named1DLutType> *property)'''
new = '''// NVIDIA's mandatory CSC0LUT/CSC1LUT stages are fixed functions whose PQ
// domain convention is not programmable and not verifiable from the DRM UAPI
// alone. The UAPI contract maps 10,000 nits to 125; NVIDIA's internal
// datapath convention maps 10,000 nits to 1.0, and the driver bridges only
// the bypassable DEGAMMA path to the UAPI (implicit 125x multiplier).
// This scale is runtime-selectable so one controlled experiment can
// determine which convention the hardware implements. Default: UAPI (125),
// which keeps stock patch 0016 behavior.
static double mandatoryCscPqScale()
{
    static const double scale = [] {
        const QByteArray value = qgetenv("KWIN_DRM_NVIDIA_CSC_PQ_SCALE");
        if (value == "1") {
            return 1.0;
        }
        return 125.0;
    }();
    return scale;
}

static std::optional<std::pair<TransferFunction::Type, bool>> pickSupportedFunction(DrmEnumProperty<Named1DLutType> *property)'''
assert old in s, "pickSupportedFunction anchor missing"
s = s.replace(old, new)

old = '''std::optional<DrmAbstractColorOp::Scaling> DrmNamed1DLut::inputScaling(const ColorOp &op) const
{'''
new = '''double DrmNamed1DLut::transferFunctionScale(TransferFunction::Type type) const
{
    if (type != TransferFunction::PerceptualQuantizer) {
        return 1.0;
    }
    // Bypassable named curves are bridged to the UAPI convention by the
    // driver (implicit degamma multiplier); their scale is always 125.
    // Mandatory fixed stages follow the runtime-selected convention.
    return m_bypass ? 125.0 : mandatoryCscPqScale();
}

std::optional<DrmAbstractColorOp::Scaling> DrmNamed1DLut::inputScaling(const ColorOp &op) const
{'''
assert old in s, "inputScaling anchor missing"
s = s.replace(old, new)

old = '''        // PQ_125 has 125 as the maximum value (instead of 10'000 or 1)
        const double transferFunctionScale = tf->tf.type == TransferFunction::PerceptualQuantizer ? 125 : 1;
        const bool rangeMatches = op.input.min >= -0.001 && op.input.max <= transferFunctionScale + 0.001;'''
new = '''        const double transferFunctionScale = this->transferFunctionScale(tf->tf.type);
        const bool rangeMatches = op.input.min >= -0.001 && op.input.max <= transferFunctionScale + 0.001;'''
assert old in s, "inputScaling PQ scale anchor missing"
s = s.replace(old, new)

old = '''        // PQ_125 has 125 as the maximum value (instead of 10'000 or 1)
        const double transferFunctionScale = tf->tf.type == TransferFunction::PerceptualQuantizer ? 125 : 1;
        const bool rangeMatches = op.output.min >= -0.001 && op.output.max <= transferFunctionScale + 0.001;'''
new = '''        const double transferFunctionScale = this->transferFunctionScale(tf->tf.type);
        const bool rangeMatches = op.output.min >= -0.001 && op.output.max <= transferFunctionScale + 0.001;'''
assert old in s, "outputScaling PQ scale anchor missing"
s = s.replace(old, new)

old = '''static double namedTransferFunctionScale(TransferFunction::Type type)
{
    // DRM's PQ 125 curve maps code value 1 to 125. The other named curves are
    // normalized to one. DrmNamed1DLut::inputScaling/outputScaling use the same
    // convention.
    return type == TransferFunction::PerceptualQuantizer ? 125.0 : 1.0;
}'''
assert old in s, "namedTransferFunctionScale anchor missing"
s = s.replace(old, "")

old = '''    const auto [type, inverse] = *function;
    const double scale = namedTransferFunctionScale(type);
    if (!inverse && (nextOperation.input.min < -ColorPipeline::s_maxResolution || nextOperation.input.max > 1.0 + ColorPipeline::s_maxResolution)) {'''
new = '''    const auto [type, inverse] = *function;
    const double scale = transferFunctionScale(type);
    if (!inverse && (nextOperation.input.min < -ColorPipeline::s_maxResolution || nextOperation.input.max > 1.0 + ColorPipeline::s_maxResolution)) {'''
assert old in s, "bypassScaling scale anchor missing"
s = s.replace(old, new)

old = '''    const auto [type, inverse] = *function;
    const double scale = namedTransferFunctionScale(type);
    const double maximumOutput = inverse ? 1.0 : scale;'''
new = '''    const auto [type, inverse] = *function;
    const double scale = transferFunctionScale(type);
    const double maximumOutput = inverse ? 1.0 : scale;'''
assert old in s, "bypassOutputScaling scale anchor missing"
s = s.replace(old, new)

cpp.write_text(s)

h = hdr.read_text()
old = '''    std::optional<Named1DLutType> getType(const ColorOp::Operation &op) const;'''
new = '''    std::optional<Named1DLutType> getType(const ColorOp::Operation &op) const;
    double transferFunctionScale(TransferFunction::Type type) const;'''
assert old in h, "header anchor missing"
hdr.write_text(h.replace(old, new))

print(f"0021 applied to {cpp} and {hdr}")
