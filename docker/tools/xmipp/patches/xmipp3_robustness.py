#!/usr/bin/env python3

"""
Ximpp3 robustness patches
=========================

Xmipp3 patches which are applied during container image build.
"""

import os
import shutil
import textwrap

SITE_PKG = os.path.join(
    os.environ.get("SCIPION_HOME", "/opt/scipion"),
    ".scipion3/lib/python3.10/site-packages",
)


def _patch_file(rel_path: str, replacements: list[tuple[str, str]]) -> None:
    """Apply a list of (old, new) literal replacements to a site-packages file."""

    full = os.path.join(SITE_PKG, rel_path)
    if not os.path.isfile(full):
        print(f"  SKIP  {rel_path} (file not found)")
        return

    orig = full + ".orig"
    if not os.path.isfile(orig):
        shutil.copy2(full, orig)

    src = open(full, "r", encoding="utf-8").read()
    patched = False
    for old, new in replacements:
        if old in src:
            src = src.replace(old, new, 1)
            patched = True
        else:
            # Check if already patched
            if new in src:
                print(f"  OK    {rel_path} (already patched)")
            else:
                print(f"  WARN  {rel_path}: expected snippet not found:\n{textwrap.indent(old[:120], '        ')}")

    if patched:
        with open(full, "w", encoding="utf-8") as f:
            f.write(src)
        print(f"  PATCH {rel_path}")


# Original crashes with TypeError when ar is None. Fixed version raises
# ValueError on None, handles zero-std gracefully.

_NORMALIZE_OLD = """\
def normalize_array(ar):
    '''Normalize values in an array with mean 0 and std deviation 1
    '''
    ar -= np.mean(ar)
    ar /= np.std(ar)
    return ar"""

_NORMALIZE_NEW = """\
def normalize_array(ar):
    '''Normalize values in an array with mean 0 and std deviation 1
    '''
    if ar is None:
        raise ValueError(
            "normalize_array: received None instead of an ndarray. "
            "This usually means the image file could not be read "
            "(check file path, format, or xmippLib bindings)."
        )
    ar = np.asarray(ar, dtype=np.float64)
    mean_val = np.mean(ar)
    std_val = np.std(ar)
    ar -= mean_val
    if std_val > 0:
        ar /= std_val
    else:
        import logging
        logging.getLogger("xmipp3.utils").warning(
            "normalize_array: std deviation is 0 - returning zero-mean array"
        )
    return ar"""


# Original does not guard against est_gain.getData() returning None.
# Fixed version checks data before proceeding, falls back gracefully.

_MATCH_ORIENT_OLD = """\
        est_gain_array = est_gain.getData()
        est_gain_array = xmutils.normalize_array(est_gain_array)
        est_gain_array_FT_conj = np.conj(np.fft.fft2(est_gain_array))"""

_MATCH_ORIENT_NEW = """\
        est_gain_array = est_gain.getData()
        if est_gain_array is None:
            self.warning(
                "Estimated gain image data is None - cannot determine "
                "orientation.  Using experimental gain as-is."
            )
            exp_data = exp_gain.getData()
            if exp_data is not None:
                xmutils.writeImageFromArray(
                    np.asarray(exp_data, dtype=np.float64),
                    self.getOrientedGainPath(),
                )
            return
        est_gain_array = xmutils.normalize_array(est_gain_array)
        est_gain_array_FT_conj = np.conj(np.fft.fft2(est_gain_array))"""

_ORIENT_STEP_OLD = """\
        estGain = xmutils.readImage(estGainFn)
        expGain = xmutils.readImage(expGainFn)
        self.match_orientation(expGain, estGain)"""

_ORIENT_STEP_NEW = """\
        if not os.path.isfile(estGainFn):
            self.warning("Estimated gain file not found: %s - skipping orientation" % estGainFn)
            return
        if not expGainFn or not os.path.isfile(expGainFn):
            self.warning("Experimental gain file not found: %s - skipping orientation" % expGainFn)
            return
        estGain = xmutils.readImage(estGainFn)
        expGain = xmutils.readImage(expGainFn)
        self.match_orientation(expGain, estGain)"""


# getPreviousParameters() crashes with TypeError when ctfRelations.get()
# returns None (e.g. upstream CTF output is empty or pointer is broken).
# Fixed version guards against None before iterating.

_CTF_PREV_OLD = """\
    def getPreviousParameters(self):
        if self.ctfRelations.hasValue():
            self.ctfDict = {}
            for ctf in self.ctfRelations.get():
                ctfName = ctf.getMicrograph().getMicName()
                self.ctfDict[ctfName] = self.getPreviousValues(ctf)"""

_CTF_PREV_NEW = """\
    def getPreviousParameters(self):
        if self.ctfRelations.hasValue():
            relations = self.ctfRelations.get()
            if relations is not None:
                self.ctfDict = {}
                for ctf in relations:
                    ctfName = ctf.getMicrograph().getMicName()
                    self.ctfDict[ctfName] = self.getPreviousValues(ctf)"""

_CTF_SINGLE_OLD = """\
    def getSinglePreviousParameters(self, micId):
        if self.ctfRelations.hasValue():
            ctf = self.ctfRelations.get()[micId]
            return self.getPreviousValues(ctf)"""

_CTF_SINGLE_NEW = """\
    def getSinglePreviousParameters(self, micId):
        if self.ctfRelations.hasValue():
            relations = self.ctfRelations.get()
            if relations is not None:
                ctf = relations[micId]
                return self.getPreviousValues(ctf)"""


# _loadSet crashes with AttributeError when self.ctfRelations.get()
# returns None (upstream CTF not yet available in pipeline mode).

_CTF_LOADSET_OLD = """        if self.doInitialCTF.get():
            ctfSet = SetOfCTF(filename=self.ctfRelations.get().getFileName())"""

_CTF_LOADSET_NEW = """        if self.doInitialCTF.get():
            _ctfRel = self.ctfRelations.get() if self.ctfRelations.hasValue() else None
            if _ctfRel is None:
                self.warning("doInitialCTF is True but ctfRelations is empty - skipping initial CTF check")
                return OrderedDict(), False
            ctfSet = SetOfCTF(filename=_ctfRel.getFileName())"""


# np.asscalar was removed in numpy 1.24+. Replace with .item().

_ASSCALAR_OLD_1 = """T = np.asarray([[1, 0, np.asscalar(corLoc[1])], [0, 1, np.asscalar(corLoc[0])], [0, 0, 1]])"""

_ASSCALAR_NEW_1 = """T = np.asarray([[1, 0, corLoc[1].item()], [0, 1, corLoc[0].item()], [0, 0, 1]])"""


# _loadSet in ProtExtractParticles._loadInputList crashes with
# AttributeError when ctfRelations.get() returns None (CTF protocol
# not yet finished). Guard the inner function to handle None gracefully.

_PARTICLES_LOADSET_OLD = """        def _loadSet(inputSet, SetClass, getKeyFunc):
            setFn = inputSet.getFileName()"""

_PARTICLES_LOADSET_NEW = """        def _loadSet(inputSet, SetClass, getKeyFunc):
            if inputSet is None:
                raise RuntimeError(
                    "ExtractParticles: required input set is None. "
                    "The upstream protocol (e.g. CTF estimation) may not have "
                    "finished yet.  Add its protocol ID to _prerequisites "
                    "in the workflow JSON to enforce correct ordering."
                )
            setFn = inputSet.getFileName()"""


# In some xmippLib builds, emlib.SymList is not exported by the SWIG
# bindings. This crashes both _insertAllSteps() and _validate() in
# XmippProtReconstructSignificant. Fix: wrap SymList calls in try/except
# with a hardcoded symmetry lookup as fallback.

_RECON_STEPS_OLD = """\
        SL = emlib.SymList()
        SL.readSymmetryFile(self.symmetryGroup.get())
        self.trueSymsNo = SL.getTrueSymsNo()
        self.TsCurrent = self.inputSet.get().getSamplingRate()"""

_RECON_STEPS_NEW = """\
        try:
            SL = emlib.SymList()
            SL.readSymmetryFile(self.symmetryGroup.get())
            self.trueSymsNo = SL.getTrueSymsNo()
        except AttributeError:
            _sym = self.symmetryGroup.get().strip().lower()
            _lookup = {'c1':0,'c2':1,'c3':2,'c4':3,'c5':4,'c6':5,
                        'd1':1,'d2':3,'d3':5,'d4':7,'d5':9,'d6':11,
                        't':11,'o':23,'i':59,'i1':59,'i2':59,'ih':59}
            if _sym in _lookup:
                self.trueSymsNo = _lookup[_sym]
            elif _sym.startswith('c') and _sym[1:].isdigit():
                self.trueSymsNo = int(_sym[1:]) - 1
            elif _sym.startswith('d') and _sym[1:].isdigit():
                self.trueSymsNo = 2 * int(_sym[1:]) - 1
            else:
                self.trueSymsNo = 0
        self.TsCurrent = self.inputSet.get().getSamplingRate()"""

_RECON_VALIDATE_OLD = """\
        SL = emlib.SymList()
        SL.readSymmetryFile(self.symmetryGroup.get())
        if (100 - self.alpha0.get()) / 100.0 * (SL.getTrueSymsNo() + 1) > 1:"""

_RECON_VALIDATE_NEW = """\
        try:
            SL = emlib.SymList()
            SL.readSymmetryFile(self.symmetryGroup.get())
            _trueSymsNo = SL.getTrueSymsNo()
        except AttributeError:
            _sym = self.symmetryGroup.get().strip().lower()
            _lookup = {'c1':0,'c2':1,'c3':2,'c4':3,'c5':4,'c6':5,
                        'd1':1,'d2':3,'d3':5,'d4':7,'d5':9,'d6':11,
                        't':11,'o':23,'i':59,'i1':59,'i2':59,'ih':59}
            if _sym in _lookup:
                _trueSymsNo = _lookup[_sym]
            elif _sym.startswith('c') and _sym[1:].isdigit():
                _trueSymsNo = int(_sym[1:]) - 1
            elif _sym.startswith('d') and _sym[1:].isdigit():
                _trueSymsNo = 2 * int(_sym[1:]) - 1
            else:
                _trueSymsNo = 0
        if (100 - self.alpha0.get()) / 100.0 * (_trueSymsNo + 1) > 1:"""


# XmippProtCreateMask3D does not override _validate(), and its inputVolume
# is declared with allowsNull=True (needed because the param is conditional
# on source == SOURCE_VOLUME). This means the parent Protocol.validate()
# skips the "cannot be EMPTY" check. When scheduling pipelines, this allows
# the scheduler to launch the protocol before the upstream volume is ready,
# crashing with "Can not convert object <class 'NoneType'> to (index, location)".
# Fix: inject a _validate method that checks inputVolume is not None when
# source is SOURCE_VOLUME. Also guards _insertAllSteps for extra safety.

_CREATEMASK3D_SUMMARY_OLD = """\
    #--------------------------- INFO functions --------------------------------------------
    def _summary(self):"""

_CREATEMASK3D_SUMMARY_NEW = """\
    #--------------------------- VALIDATION functions --------------------------------------
    def _validate(self):
        errors = []
        if self.source == SOURCE_VOLUME:
            vol = self.inputVolume.get()
            if vol is None:
                errors.append("*Input volume* cannot be EMPTY.  "
                              "The upstream protocol that produces the volume "
                              "may not have finished yet.")
        return errors

    #--------------------------- INFO functions --------------------------------------------
    def _summary(self):"""

_CREATEMASK3D_STEPS_OLD = """\
    def _insertAllSteps(self):
        self.maskFile = self._getPath('mask.mrc')

        if self.source == SOURCE_VOLUME:
            self._insertFunctionStep('createMaskFromVolumeStep')"""

_CREATEMASK3D_STEPS_NEW = """\
    def _insertAllSteps(self):
        self.maskFile = self._getPath('mask.mrc')

        if self.source == SOURCE_VOLUME:
            if self.inputVolume.get() is None:
                raise RuntimeError(
                    "XmippProtCreateMask3D: inputVolume is None. "
                    "The upstream protocol (e.g. initial model) has not "
                    "produced output yet. Check _prerequisites in the "
                    "workflow JSON to enforce correct ordering."
                )
            self._insertFunctionStep('createMaskFromVolumeStep')"""


# _libNone.Image (the ghost fallback when xmippLib is absent) is missing
# write, convert2DataType, applyTransforMatScipion, getData, setData,
# readPreview. ImageHandler.convert() crashes with AttributeError.
# Add these as safe no-ops so protocols get a clean error instead.
_LIBNONE_IMAGE_OLD = """\
class Image:
    def __init__(self):
        pass

    def read(self, *args, **kwargs):
        print("GHOST in place, read call ignored!.")

    def getDimensions(self):
        return None, None, None, None"""

_LIBNONE_IMAGE_NEW = """\
class Image:
    def __init__(self):
        self._d = None

    def read(self, *args, **kwargs):
        print("GHOST in place, read call ignored!.")

    def write(self, *args, **kwargs):
        pass

    def convert2DataType(self, *args, **kwargs):
        pass

    def applyTransforMatScipion(self, *args, **kwargs):
        pass

    def getData(self):
        return self._d

    def setData(self, data):
        self._d = data

    def readPreview(self, *args, **kwargs):
        pass

    def getDimensions(self):
        return None, None, None, None"""


# updateGainsOutput() appends Image(movieId) to a gain set that is reloaded
# from SQLite each _checkNewOutput cycle. When the protocol restarts
# processing (like after a job pod reschedule) the set already contains
# the item from the previous run, causing sqlite3.IntegrityError: UNIQUE constraint
# failed: Objects.id Fix: try append, on IntegrityError fall back to update.

_MOVGAIN_APPEND_OLD = """\
        imgSet.setSamplingRate(movie.getSamplingRate())
        imgSet.append(imgOut)
        return imgSet"""

_MOVGAIN_APPEND_NEW = """\
        imgSet.setSamplingRate(movie.getSamplingRate())
        try:
            imgSet.append(imgOut)
        except Exception:
            imgSet.update(imgOut)
        return imgSet"""


# In Kubernetes the protocol PID belongs to a different pod (job pod) or
# to a previous GUI pod incarnation. psutil.Process(pid) raises
# psutil.NoSuchProcess -> stop() raises -> resetProtocol raises ->
# UI shows "Error while resetting the workflow with: <protocol>".
# Fix: wrap the whole function in a try/except that catches NoSuchProcess
# and AccessDenied so that reset and stop work gracefully.

_KILLWITHCHILDS_OLD = """\
def killWithChilds(pid):
    \"\"\" Kill the process with given pid and all children processes.

    :param pid: the process id to terminate
    \"\"\"
    proc = psutil.Process(pid)
    for c in proc.children(recursive=True):
        if c.pid is not None:
            logger.info("Terminating child pid: %d" % c.pid)
            c.kill()
    logger.info("Terminating process pid: %s" % pid)
    if pid is None:
        logger.warning("Got None PID!!!")
    else:
        proc.kill()"""

_KILLWITHCHILDS_NEW = """\
def killWithChilds(pid):
    \"\"\" Kill the process with given pid and all children processes.

    :param pid: the process id to terminate
    \"\"\"
    if pid is None:
        logger.warning("Got None PID!!!")
        return
    try:
        proc = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        logger.info("Process pid %s not found (may run on another host) - skipping kill" % pid)
        return
    for c in proc.children(recursive=True):
        if c.pid is not None:
            try:
                logger.info("Terminating child pid: %d" % c.pid)
                c.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    logger.info("Terminating process pid: %s" % pid)
    try:
        proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass"""


# The cancel command (_run(cancelCmd)) can fail if job already finished
# or the controller is unreachable. This raises and blocks protocol reset.

_STOP_OLD = """\
def stop(protocol):
    \"\"\"
    Stop function for three scenarios:
    - If the queue is not used, kill the main protocol process and its child processes.
    - If the queue is used and the entire protocol is sent to the queue, cancel the job running the protocol using
    scancel.
    - If the queue is used and individual steps are sent to the queue, cancel all active jobs and kill the main protocol
    process and its child processes.
    \"\"\"
    if protocol.useQueue() and not protocol.isScheduled():
        jobIds = protocol.getJobIds()
        for jobId in jobIds: # Iter even though it contains only one jobId
            host = protocol.getHostConfig()
            cancelCmd = host.getCancelCommand() % {'JOB_ID': jobId}
            logger.info(cancelCmd)
            _run(cancelCmd, wait=True)

        if protocol.useQueueForSteps():
            process.killWithChilds(protocol.getPid())
    else:
        process.killWithChilds(protocol.getPid())"""

_STOP_NEW = """\
def stop(protocol):
    \"\"\"
    Stop function for three scenarios:
    - If the queue is not used, kill the main protocol process and its child processes.
    - If the queue is used and the entire protocol is sent to the queue, cancel the job running the protocol using
    scancel.
    - If the queue is used and individual steps are sent to the queue, cancel all active jobs and kill the main protocol
    process and its child processes.
    \"\"\"
    if protocol.useQueue() and not protocol.isScheduled():
        jobIds = protocol.getJobIds()
        for jobId in jobIds: # Iter even though it contains only one jobId
            host = protocol.getHostConfig()
            cancelCmd = host.getCancelCommand() % {'JOB_ID': jobId}
            logger.info(cancelCmd)
            try:
                _run(cancelCmd, wait=True)
            except Exception:
                logger.warning("Cancel command failed for job %s - ignoring" % jobId)

        if protocol.useQueueForSteps():
            process.killWithChilds(protocol.getPid())
    else:
        process.killWithChilds(protocol.getPid())"""


def main():
    print(f"Applying xmipp3 robustness patches to {SITE_PKG}")

    _patch_file("xmipp3/utils.py", [(_NORMALIZE_OLD, _NORMALIZE_NEW)])
    _patch_file(
        "xmipp3/protocols/protocol_movie_gain.py",
        [
            (_MATCH_ORIENT_OLD, _MATCH_ORIENT_NEW),
            (_ORIENT_STEP_OLD, _ORIENT_STEP_NEW),
            (_ASSCALAR_OLD_1, _ASSCALAR_NEW_1),
            (_ASSCALAR_OLD_1, _ASSCALAR_NEW_1),
            (_MOVGAIN_APPEND_OLD, _MOVGAIN_APPEND_NEW),
        ],
    )
    _patch_file(
        "xmipp3/protocols/protocol_ctf_micrographs.py",
        [
            (_CTF_PREV_OLD, _CTF_PREV_NEW),
            (_CTF_SINGLE_OLD, _CTF_SINGLE_NEW),
            (_CTF_LOADSET_OLD, _CTF_LOADSET_NEW),
        ],
    )
    _patch_file(
        "pwem/protocols/protocol_particles.py",
        [
            (_PARTICLES_LOADSET_OLD, _PARTICLES_LOADSET_NEW),
        ],
    )
    _patch_file(
        "xmipp3/protocols/protocol_reconstruct_significant.py",
        [
            (_RECON_STEPS_OLD, _RECON_STEPS_NEW),
            (_RECON_VALIDATE_OLD, _RECON_VALIDATE_NEW),
        ],
    )
    _patch_file(
        "xmipp3/protocols/protocol_preprocess/protocol_create_mask3d.py",
        [
            (_CREATEMASK3D_SUMMARY_OLD, _CREATEMASK3D_SUMMARY_NEW),
            (_CREATEMASK3D_STEPS_OLD, _CREATEMASK3D_STEPS_NEW),
        ],
    )
    _patch_file(
        "pwem/emlib/_libNone.py",
        [
            (_LIBNONE_IMAGE_OLD, _LIBNONE_IMAGE_NEW),
        ],
    )
    _patch_file(
        "pyworkflow/utils/process.py",
        [
            (_KILLWITHCHILDS_OLD, _KILLWITHCHILDS_NEW),
        ],
    )
    _patch_file(
        "pyworkflow/protocol/launch.py",
        [
            (_STOP_OLD, _STOP_NEW),
        ],
    )
    print("Done.")


if __name__ == "__main__":
    main()
