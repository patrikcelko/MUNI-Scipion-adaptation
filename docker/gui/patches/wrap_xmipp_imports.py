#!/usr/bin/env python3

"""
xmipp3 protocols wrapper
========================

Wrap 'from .protocol_*' imports in xmipp3/protocols/__init__.py with try/except.
"""

import re
import sys

init_path = sys.argv[1]

with open(init_path, 'r') as f:
    lines = f.readlines()

out = []
i = 0
while i < len(lines):
    line = lines[i]

    # Pass through existing try blocks unchanged
    if line.strip() == 'try:':
        out.append(line)
        i += 1

        while i < len(lines):
            out.append(lines[i])
            if lines[i].strip() == 'pass' and i > 0 and 'except' in lines[i - 1]:
                i += 1
                break
            i += 1

        continue

    # Wrap bare protocol imports
    if re.match(r'^from \.protocol_', line):
        imp = [line]
        op = sum(lin.count('(') - lin.count(')') for lin in imp)

        while (line.rstrip().endswith(',') or op > 0) and i + 1 < len(lines):
            i += 1
            line = lines[i]
            imp.append(line)
            op += line.count('(') - line.count(')')

        out.append('try:\n')
        out.extend('    ' + lin for lin in imp)
        out.append('except Exception:\n')
        out.append('    pass\n')
    else:
        out.append(line)

    i += 1

with open(init_path, 'w') as f:
    f.writelines(out)

print(f'Wrapped xmipp3 protocol imports in try/except ({init_path})')
