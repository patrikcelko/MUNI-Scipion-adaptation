#!/usr/bin/env python3

"""
Stub xmippLib
=============

The real xmippLib comes with a full Xmipp installation. Since the GUI container only needs
Python wrappers (protocols run in job containers), this stub satisfies import-time references
so xmipp3.protocols loads correctly. Then actual xmippLib calls only happen at protocol
runtime, which executes in job containers that have the real Xmipp + xmippLib installed.
"""


class Image:
    """Stub for xmippLib.Image"""

    def __init__(self, *args, **kwargs):
        pass

    def getData(self):
        return None

    def setData(self, *args):
        pass

    def write(self, *args):
        pass

    def read(self, *args):
        pass

    def readPreview(self, *args):
        pass


class MetaData:
    """Stub for xmippLib.MetaData"""

    def __init__(self, *args, **kwargs):
        pass

    def __iter__(self):
        return iter([])

    def __len__(self):
        return 0

    def size(self):
        return 0

    def isEmpty(self):
        return True

    def getValue(self, *args, **kwargs):
        return None

    def setValue(self, *args, **kwargs):
        pass

    def getRow(self, *args, **kwargs):
        return None

    def addObject(self, *args, **kwargs):
        return 0

    def firstObject(self, *args, **kwargs):
        return None

    def write(self, *args):
        pass

    def read(self, *args):
        pass


class FileName:
    """Stub for xmippLib.FileName"""

    # Image format extensions recognized by Xmipp
    _IMAGE_EXTS = frozenset([
        'img', 'hed', 'inf', 'raw', 'mrc', 'map', 'spi', 'xmp',
        'tif', 'tiff', 'gain', 'dm3', 'spe', 'em', 'pif', 'ser',
        'stk', 'mrcs', 'jpg', 'dm4', 'hdf', 'h5', 'eer', 'mha',
    ])
    _STACK_EXTS = frozenset([
        'stk', 'spi', 'xmp', 'mrcs', 'mrc', 'img', 'hed', 'pif',
        'tif', 'tiff', 'dm3', 'ser', 'st', 'dm4', 'eer',
    ])
    _VOLUME_EXTS = frozenset([
        'vol', 'spi', 'xmp', 'mrc', 'map', 'em', 'pif', 'inf', 'raw',
    ])
    _METADATA_EXTS = frozenset([
        'sel', 'xmd', 'doc', 'ctfdat', 'ctfparam', 'pos',
        'sqlite', 'xml', 'star',
    ])

    def __init__(self, path=''):
        if isinstance(path, FileName):
            self._path = path._path
        else:
            self._path = str(path) if path else ''

    def __str__(self):
        return self._path

    def __repr__(self):
        return f"FileName('{self._path}')"

    def __bool__(self):
        return bool(self._path)

    def __eq__(self, other):
        if isinstance(other, FileName):
            return self._path == other._path

        return self._path == str(other)

    def __hash__(self):
        return hash(self._path)

    def getExtension(self):
        """Return last extension without dot, e.g. 'tiff'."""

        import os  # Needs to be imported here

        base = os.path.basename(self._path)
        if '.' in base:
            return base.rsplit('.', 1)[1]

        return ''

    def getFileFormat(self):
        """Return the file format (after ':' or last extension), lower-cased."""

        if ':' in self._path:
            return self._path.rsplit(':', 1)[1].lower()

        ext = self.getExtension()
        if '#' in ext:
            ext = ext.split('#', 1)[0]

        return ext.lower()

    def hasImageExtension(self):
        return self.getFileFormat() in self._IMAGE_EXTS

    def hasStackExtension(self):
        return self.getFileFormat() in self._STACK_EXTS

    def hasVolumeExtension(self):
        return self.getFileFormat() in self._VOLUME_EXTS

    def hasMetadataExtension(self):
        return self.getFileFormat() in self._METADATA_EXTS

    def isImage(self):
        """Check if the filename has a recognized image extension."""

        return self.hasImageExtension()

    def isMetaData(self, failIfNotExists=True):
        if not self._path or ':' in self._path or '#' in self._path:
            return False

        return self.hasMetadataExtension()

    def decompose(self):
        """Parse 'NNN@filename' -> (index, filename)"""

        if '@' in self._path:
            parts = self._path.split('@', 1)
            try:
                idx = int(parts[0].rstrip(',').split(',')[-1])
                return (idx, parts[1])
            except (ValueError, IndexError):
                pass

        return (0, self._path)

    def compose(self, *args):
        """compose(root, number, ext) or compose(number, filename) or compose(blockname, filename)."""

        if len(args) == 2:
            a, b = args

            if isinstance(a, int):
                self._path = '%06d@%s' % (a, b)
            elif isinstance(a, str) and a:
                self._path = '%s@%s' % (a, b)
            else:
                self._path = str(b)
        elif len(args) == 3:
            root, no, ext = args
            self._path = '%s%06d' % (root, no)

            if ext:
                self._path += '.%s' % ext
        elif len(args) == 1:
            self._path = str(args[0])

        return self._path

    def getBlockName(self):
        """Return block name before '@', or '' if none."""

        if '@' in self._path:
            prefix = self._path.split('@', 1)[0]

            if prefix and prefix[0].isalpha():
                return prefix

        return ''

    def removeBlockName(self):
        """Return filename part after '@'."""

        if '@' in self._path:
            return FileName(self._path.split('@', 1)[1])

        return FileName(self._path)

    def removeFileFormat(self):
        """Remove ':format' or '#...' suffix."""

        path = self._path
        for sep in ('#', ':'):
            idx = path.rfind(sep)

            if idx != -1:
                path = path[:idx]

        return FileName(path)

    def removeAllPrefixes(self):
        """Remove 'NNN@' prefix."""

        if '@' in self._path:
            return FileName(self._path.split('@', 1)[1])

        return FileName(self._path)

    def withoutExtension(self):
        """Remove last extension."""

        idx = self._path.rfind('.')
        if idx != -1:
            return FileName(self._path[:idx])

        return FileName(self._path)

    def addExtension(self, ext):
        if ext:
            return FileName(self._path + '.' + ext)
        return FileName(self._path)

    def removeLastExtension(self):
        return self.withoutExtension()

    def exists(self):
        """Check if the file exists on disk."""

        import os  # Needs to be imported here

        cleaned = self.removeAllPrefixes().removeFileFormat()
        return os.path.isfile(str(cleaned))

    def getDecomposedFileName(self):
        _, fn = self.decompose()
        return FileName(fn)

    def getNumber(self):
        """Get number from base name (e.g. 'img000005.mrc' -> 5)."""

        import re  # Needs to be imported here

        base = self._path.rsplit('.', 1)[0] if '.' in self._path else self._path
        m = re.search(r'(\d+)$', base)

        return int(m.group(1)) if m else -1

    def getPrefixNumber(self):
        """Get prefix number before '@'."""

        if '@' in self._path:
            try:
                return int(self._path.split('@', 1)[0])
            except ValueError:
                pass

        return 0

    def isInStack(self):
        return '@' in self._path

    def isEmpty(self):
        return self._path == ''

    def getString(self):
        return self._path

    def contains(self, sub):
        return sub in self._path

    def removeFilename(self):
        """Return directory part."""

        import os  # Needs to be imported here

        return FileName(os.path.dirname(self._path))

    def removeAllExtensions(self):
        """Remove all extensions from filename."""

        import os  # Needs to be imported here

        base = os.path.basename(self._path)
        dirn = os.path.dirname(self._path)
        if '.' in base:
            base = base.split('.', 1)[0]

        return FileName(os.path.join(dirn, base)) if dirn else FileName(base)


class Program:
    """Stub for xmippLib.Program"""

    def __init__(self, *args, **kwargs):
        pass


def createEmptyFile(*args, **kwargs):
    """Stub for xmippLib.createEmptyFile"""
    pass


def getBlocksInMetaDataFile(*args, **kwargs):
    return []


def label2Str(*args, **kwargs):
    return ""


def colorStr(*args, **kwargs):
    return ""


def labelType(*args, **kwargs):
    return 0


def labelHasTag(*args, **kwargs):
    return False


def labelIsImage(*args, **kwargs):
    return False


def str2Label(*args, **kwargs):
    return 0


def isValidLabel(*args, **kwargs):
    return False


def MDValueRelational(*args, **kwargs):
    return None


def MDValueEQ(*args, **kwargs):
    return None


def MDValueNE(*args, **kwargs):
    return None


def MDValueLT(*args, **kwargs):
    return None


def MDValueLE(*args, **kwargs):
    return None


def MDValueGT(*args, **kwargs):
    return None


def MDValueGE(*args, **kwargs):
    return None


def MDValueRange(*args, **kwargs):
    return None


def addLabelAlias(*args, **kwargs):
    pass


def activateMathExtensions(*args, **kwargs):
    pass
