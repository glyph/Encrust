from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
from tempfile import NamedTemporaryFile
from typing import AsyncIterable, Iterable

from ._spawnutil import c, parallel
from twisted.internet.defer import Deferred
from twisted.python.filepath import FilePath
from twisted.python.procutils import which
from wheel_filename import ParsedWheelFilename, parse_wheel_filename


class KnownArchitecture(Enum):
    """
    One of the known binary architectures that a wheel can support on macOS;
    intel, arm, both, or pure-python.
    """
    x86_64 = auto()
    arm64 = auto()
    universal2 = auto()
    purePython = auto()


@dataclass(frozen=True)
class PlatformSpecifics:
    """
    A data structure representing the specific details of a macOS platform
    description for a python wheel; i.e. operating system version and binary
    architecture.
    """

    os: str
    major: int
    minor: int
    architecture: KnownArchitecture


def specifics(pwf: ParsedWheelFilename) -> Iterable[PlatformSpecifics]:
    """
    Enumerate the specific macOS platforms supported by a given wheel based on
    its filename.
    """
    for tag in pwf.platform_tags:
        splitted = tag.split("_", 3)
        print("split", splitted)
        if len(splitted) != 4:
            continue
        os, major, minor, arch = splitted
        try:
            parsedArch = KnownArchitecture[arch]
        except ValueError:
            continue
        yield PlatformSpecifics(os, int(major), int(minor), parsedArch)


def wheelNameArchitecture(pwf: ParsedWheelFilename) -> KnownArchitecture:
    """
    Determine the architecture from a wheel.
    """
    if pwf.abi_tags == ["none"] and pwf.platform_tags == ["any"]:
        return KnownArchitecture.purePython
    allSpecifics = list(specifics(pwf))
    if len(allSpecifics) != 1:
        raise ValueError(
            f"don't know how to handle multi-tag wheels {pwf!r} {allSpecifics!r}"
        )
    return allSpecifics[0].architecture


@dataclass
class FusedPair:
    arm64: FilePath[str] | None = None
    x86_64: FilePath[str] | None = None
    universal2: FilePath[str] | None = None


async def findSingleArchitectureBinaries(
    paths: Iterable[FilePath[str]],
) -> AsyncIterable[FilePath[str]]:
    """
    Find any binaries under a given path that are single-architecture (i.e.
    those that will not run on an older Mac because they're fat binary).
    """
    checkedSoFar = 0

    async def checkOne(path: FilePath[str]) -> tuple[FilePath[str], bool]:
        """
        Check the given path for a single-architecture binary, returning True
        if it is one and False if not.
        """
        nonlocal checkedSoFar
        if path.islink():
            return path, False
        if not path.isfile():
            return path, False
        checkedSoFar += 1
        # universal binaries begin "Mach-O universal binary with 2 architectures"
        if (checkedSoFar % 1000) == 0:
            print("?", end="", flush=True)
        isSingle = (await c.file("-b", path.path, quiet=True)).output.startswith(
            b"Mach-O 64-bit bundle"
        )
        return path, isSingle

    async for eachPath, isSingleBinary in parallel(
        (
            checkOne(subpath)
            for path in paths
            for subpath in path.walk(
                # if we are in a virtualenv, but our system site packages has
                # single-architecture binaries installed, we should not be
                # concerned with those, as they're not on our import path -
                # even though they *do* live below an entry on sys.path (the
                # stdlib).
                lambda sub: sub.basename()
                != "site-packages"
            )
        ),
        16,
    ):
        if isSingleBinary:
            yield eachPath


def determineNeedsFusing(
    downloadDir: str, fusedDir: str
) -> Iterable[tuple[tuple[str, str], FusedPair]]:
    needsFusing: defaultdict[tuple[str, str], FusedPair] = defaultdict(FusedPair)

    for child in FilePath(downloadDir).children():
        # every wheel in this list should either be architecture-independent,
        # universal2, *or* have *both* arm64 and x86_64 versions.
        pwf = parse_wheel_filename(child.basename())
        arch = wheelNameArchitecture(pwf)
        fusedPath = FilePath(fusedDir).child(child.basename())
        if arch == KnownArchitecture.purePython:
            child.moveTo(fusedPath)
            continue
        # OK we need to fuse a wheel
        fusor = needsFusing[(pwf.project, pwf.version)]
        if arch == KnownArchitecture.x86_64:
            fusor.x86_64 = child
        if arch == KnownArchitecture.arm64:
            fusor.arm64 = child
        if arch == KnownArchitecture.universal2:
            child.moveTo(fusedPath)
            fusor.universal2 = fusedPath
    return needsFusing.items()


async def fuseOne(
    tmpDir: str, fusedDir: str, name: str, version: str, fusor: FusedPair
) -> None:
    if fusor.universal2 is not None:
        print(f"{name} has universal2; skipping")
        return

    left = fusor.arm64
    if left is None:
        raise RuntimeError(f"no arm64 architecture for {name}")
    right = fusor.x86_64
    if right is None:
        raise RuntimeError(f"no x86_64 architecture for {name}")
    await c["delocate-merge"](
        "--verbose", f"--wheel-dir={fusedDir}", left.path, right.path
    )


async def fixArchitectures() -> None:
    """
    Ensure that all wheels installed in the current virtual environment are
    universal2, not x86_64 or arm64.

    This probably only works on an arm64 (i.e., Apple Silicon) machine since it
    requires the ability to run C{pip} under both architectures.
    """
    downloadDir = ".wheels/downloaded"
    tmpDir = ".wheels/tmp"
    fusedDir = ".wheels/fused"

    output = (await c.pip("freeze")).output.decode("utf-8")
    with NamedTemporaryFile(delete=False) as f:
        for line in output.split("\n"):
            if (":" not in line) and ("/" not in line) and (not line.startswith("-e")):
                f.write((line + "\n").encode("utf-8"))

    await c.mkdir("-p", downloadDir, fusedDir, tmpDir)
    for arch in ["arm64", "x86_64"]:
        await c.arch(
            f"-{arch}",
            which("pip")[0],
            "wheel",
            "-r",
            f.name,
            "-w",
            downloadDir,
        )

    async for each in parallel(
        fuseOne(tmpDir, fusedDir, name, version, fusor)
        for ((name, version), fusor) in determineNeedsFusing(downloadDir, fusedDir)
    ):
        pass

    await c.pip(
        "install",
        "--no-index",
        "--find-links",
        fusedDir,
        "--force",
        "--requirement",
        f.name,
    )


start = Deferred.fromCoroutine


async def validateArchitectures(
    paths: Iterable[FilePath[str]], report: bool = True
) -> bool:
    """
    Ensure that there are no problematic single-architecture binaries in a
    given directory.
    """
    success = True
    async for eachBinary in findSingleArchitectureBinaries(paths):
        if (
            # exclude py2app prebuilt executable stubs
            (
                eachBinary.basename() in {"main-x86_64", "main-arm64"}
                and eachBinary.parent().basename() == "prebuilt"
            )
            or
            # exclude debugpy attach stubs
            (
                eachBinary.basename() == "attach_x86_64.dylib"
                and eachBinary.parent().basename() == "pydevd_attach_to_process"
            )
            or
            # exclude delocate's own tests
            (
                eachBinary.parent().basename() == "data"
                and eachBinary.parent().parent().basename() == "tests"
                and eachBinary.parent().parent().parent().basename() == "delocate"
            )
        ):
            continue
        if report:
            print()
            print(f"single-architecture binary: {eachBinary.path}")
        success = False
    return success
