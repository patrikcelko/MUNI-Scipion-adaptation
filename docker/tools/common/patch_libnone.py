#!/usr/bin/env python3

"""
Patch for _libNone.Image
========================

Adds stub implementations for Image methods missing from some Scipion versions
(write, convert2DataType, applyTransforMatScipion, getData, setData, readPreview).
Without these stubs, ImageHandler.convert() raises AttributeError when xmippLib
is unavailable.
"""

import glob
import os
import sys

SCIPION_HOME = os.environ.get("SCIPION_HOME", "/opt/scipion")
_PATTERN = os.path.join(SCIPION_HOME, ".scipion3", "lib", "python*/site-packages/pwem/emlib/_libNone.py")

hits = glob.glob(_PATTERN)
if not hits:
    print(f"patch_libnone: no file matching {_PATTERN!r} - skipping", file=sys.stderr)
    sys.exit(0)

target = hits[0]
content = open(target, encoding="utf-8").read()

if "def write" in content:
    print(f"patch_libnone: {target} already patched - OK")
    sys.exit(0)

_PATCH = (
    "\n# K8s robustness: missing Image methods\n"
    "Image.write = lambda self, *a: None\n"
    "Image.convert2DataType = lambda self, *a: None\n"
    "Image.applyTransforMatScipion = lambda self, *a: None\n"
    "Image.getData = lambda self: None\n"
    "Image.setData = lambda self, d: None\n"
    "Image.readPreview = lambda self, *a: None\n"
)

open(target, "w", encoding="utf-8").write(content + _PATCH)
print(f"patch_libnone: patched {target}")
