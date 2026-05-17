#!/usr/bin/env python3

"""
xmippLib and xmipp_base stub
============================
"""

import sys
import os
import re


def build_xmipplib_stub(site_packages, stub_file):
    lib_none_path = os.path.join(site_packages, 'pwem', 'emlib', '_libNone.py')

    # Extract ONLY constant assignments from _libNone.py (skip functions, imports, etc.)
    constants = []
    with open(lib_none_path, 'r') as f:
        for line in f:
            # Match lines like: CONSTANT_NAME = None (or other simple value)
            if re.match(r'^[A-Z][A-Z0-9_]+ = ', line):
                constants.append(line)

    # Read our custom stubs
    with open(stub_file, 'r') as f:
        custom_stubs = f.read()

    # Combine into xmippLib/__init__.py
    xmipplib_dir = os.path.join(site_packages, 'xmippLib')
    os.makedirs(xmipplib_dir, exist_ok=True)

    with open(os.path.join(xmipplib_dir, '__init__.py'), 'w') as f:
        f.write('# Auto-generated xmippLib stub for GUI container\n')
        f.write('# Constants from pwem/emlib/_libNone.py\n\n')
        f.writelines(constants)
        f.write('\n# Custom class and function stubs\n\n')
        f.write(custom_stubs)

    print(f'Created xmippLib stub with {len(constants)} constants + custom stubs')


def build_xmipp_base_stub(site_packages):
    """Create xmipp_base stub module providing isMdEmpty and other needed functions."""

    xmipp_base_dir = os.path.join(site_packages, 'xmipp_base')
    os.makedirs(xmipp_base_dir, exist_ok=True)

    stub_content = '''
def isMdEmpty(filename):
    """Check if a metadata file is empty. Stub always returns True."""

    return True

def createMetaDataFromPattern(*args, **kwargs):
    """Stub for createMetaDataFromPattern."""

    return None

class XmippScript:
    """Stub for XmippScript."""

    def __init__(self, *args, **kwargs):
        pass

    def defineParams(self):
        pass

    def readParams(self):
        pass

    def run(self):
        pass

class CondaEnvManager:
    """Stub CondaEnvManager."""

    @classmethod
    def yieldInstallAllCmds(cls, *args, **kwargs):
        yield ('echo "Stub xmipp_base - no real installation"', 'void.target')
'''

    with open(os.path.join(xmipp_base_dir, '__init__.py'), 'w') as f:
        f.write(stub_content)

    print('Created xmipp_base stub with isMdEmpty')


def patch_xmipp_protocols_init(site_packages):
    """Wrap imports that may still fail in try/except."""

    init_path = os.path.join(site_packages, 'xmipp3', 'protocols', '__init__.py')

    # Modules known to have additional import issues beyond xmippLib/xmipp_base
    FRAGILE_MODULES = {
        'protocol_align_volume',
        'protocol_simulate_ctf',
        'protocol_compute_likelihood',
        'protocol_structure_map_zernike3d',
        'protocol_structure_map',
    }

    with open(init_path, 'r') as f:
        lines = f.readlines()

    output = []
    for line in lines:
        needs_wrap = False

        for mod in FRAGILE_MODULES:
            if re.match(rf'^from \.{mod}\s', line) or re.match(rf'^from \.{mod}$', line.rstrip()):
                needs_wrap = True
                break

        if needs_wrap:
            output.append('try:\n')
            output.append(f'    {line}')
            output.append('except ImportError:\n')
            output.append('    pass\n')
        else:
            output.append(line)

    with open(init_path, 'w') as f:
        f.writelines(output)

    print("Patched xmipp3/protocols/__init__.py")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(f'Usage: {sys.argv[0]} <site_packages_dir> <xmippLib_stub.py>')
        sys.exit(1)

    site_packages = sys.argv[1]
    stub_file = sys.argv[2]

    build_xmipplib_stub(site_packages, stub_file)
    build_xmipp_base_stub(site_packages)
    patch_xmipp_protocols_init(site_packages)
    print("All stubs and patches applied successfully")
