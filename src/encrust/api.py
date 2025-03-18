from __future__ import annotations

import sys
from dataclasses import dataclass
from os import environ
from pathlib import Path
from typing import Mapping, Sequence

from ._spawnutil import c


@dataclass(frozen=True)
class SparkleFrameworkInfo:
    frameworkPath: Path
    downloadURL: str
    archivePath: Path

    @classmethod
    def fromVersion(cls, version: str) -> SparkleFrameworkInfo:
        home = environ["HOME"]
        qualname = f"Sparkle-{version}"
        archive = f"{qualname}.tar.xz"
        versionDir = Path(f"{home}/.local/firstparty/sparkle-project.org/{qualname}")
        return cls(
            frameworkPath=versionDir / "Sparkle.framework",
            downloadURL=f"https://github.com/sparkle-project/Sparkle/releases/download/{version}/{archive}",
            archivePath=versionDir / archive,
        )

    async def download(self) -> None:
        """
        Download the given version of the Sparkle framework and unpack it into
        a known location (asynchronously, by spawning subprocesses using a
        Twisted reactor).
        """
        archiveDownloadPath = str(self.archivePath.parent)
        await c.mkdir("-p", archiveDownloadPath)
        await c.curl("-LO", self.downloadURL, workingDirectory=archiveDownloadPath)
        await c.tar("xf", self.archivePath.name, workingDirectory=archiveDownloadPath)


@dataclass(frozen=True)
class AppCastDeployment:
    """
    Configuration values for deploying to an appcast hosted on a web server
    that we can rsync a local directory to.

    @note: hopefully obviously, rsync-to-a-directory is not the most robust
        deployment mechanism and we should probably have other ways of managing
        the input to the appcast.
    """

    privateKeyAccount: str
    localUpdatesFolder: Path
    remoteHost: str
    remotePath: str

    async def deploy(self, fwinfo: SparkleFrameworkInfo) -> None:
        self.localUpdatesFolder.mkdir(parents=True, exist_ok=True)
        for release in Path("dist").glob("*.release.app.zip"):
            target = self.localUpdatesFolder / release.name
            if target.exists():
                raise RuntimeError(f"version conflict for {release}")
            release.rename(target)
        await c[str(fwinfo.frameworkPath.parent / "bin" / "generate_appcast")](
            "--account", self.privateKeyAccount, str(self.localUpdatesFolder)
        )
        await c.rsync(
            "-avz",
            # NB: homebrew version required, since this is a new feature as of
            # 2020 and apple always insist on core utilities being decades out
            # of date
            "--mkpath",
            "--delete",
            str(self.localUpdatesFolder).rstrip("/") + "/",
            f"{self.remoteHost}:{self.remotePath.rstrip('/')}/",
        )


@dataclass
class SparkleData:
    publicEDKey: str
    feedURL: str
    sparkleFramework: SparkleFrameworkInfo
    deployment: AppCastDeployment

    def plist(self) -> Mapping[str, str]:
        return {"SUPublicEDKey": self.publicEDKey, "SUFeedURL": self.feedURL}

    @classmethod
    def withConfig(
        cls,
        *,
        sparkleVersion: str,
        publicEDKey: str,
        feedURL: str,
        keychainAccount: str,
        localUpdatesFolder: Path,
        remoteHost: str,
        remotePath: str,
    ) -> SparkleData:
        self = cls(
            publicEDKey=publicEDKey,
            feedURL=feedURL,
            sparkleFramework=SparkleFrameworkInfo.fromVersion(sparkleVersion),
            deployment=AppCastDeployment(
                privateKeyAccount=keychainAccount,
                localUpdatesFolder=localUpdatesFolder,
                remoteHost=remoteHost,
                remotePath=remotePath,
            ),
        )
        return self

    async def deploy(self) -> None:
        await self.deployment.deploy(self.sparkleFramework)


def _prefix(p: Path, fx: str) -> Path:
    return p.parent / (fx + p.name)


@dataclass(kw_only=True)
class AppDescription:
    """
    An L{AppDescription} is a high-level description of an application.
    """

    bundleID: str
    bundleName: str
    icnsFile: Path
    mainPythonScript: Path

    dataFiles: Sequence[Path] = ()
    otherFrameworks: Sequence[Path] = ()
    dockIconAtStart: bool = True
    sparkleData: SparkleData | None = None

    def varyBundleForTesting(self) -> AppDescription:
        """
        Add 'Ci' and 'Test' variants based on the environment variables:

            1. C{CI_MODE}, which can be set for running in e.g. Github Actions
               continuous integration, and

            2. C{TEST_MODE}, for generating an interactive version of the
               bundle intended to test specific functionality.

        If one of these variables is set, a few changes will be made to the
        build configuration:

            1. The bundle's name will have either 'Ci' or 'Test' prepended to
               it.

            2. the bundle's identifier will have 'test' or 'ci' prepended to
               its last dotted segment.

            3. the bundle's script will be changed to have 'Ci' or 'Test'
               prepended (so a sibling script should exist with that name).

            4. the bundle's icon file name will have 'Test' or 'Ci' prepended
               to it, similar to the script.

            5. the bundle will not include metadata about the Sparkle
               framework, as it should not be updated or deployed publicly.
        """

        def check_mode() -> str:
            match environ:
                case {"CI_MODE": b}:
                    if b:
                        return "Ci"
                case {"TEST_MODE": b}:
                    if b:
                        return "Test"
            return ""

        mode = check_mode()
        if mode == "":
            return self

        return AppDescription(
            bundleID=".".join(
                [
                    *(segments := self.bundleID.split("."))[:-1],
                    mode + segments[-1],
                ]
            ),
            bundleName=mode + self.bundleName,
            icnsFile=_prefix(self.icnsFile, mode),
            mainPythonScript=_prefix(self.mainPythonScript, mode),
            dataFiles=self.dataFiles,
            otherFrameworks=self.otherFrameworks,
            dockIconAtStart=self.dockIconAtStart,
            sparkleData=None,
        )

    def setupOptions(self) -> dict[str, object]:
        """
        Create a collection of arguments to L{setuptools.setup}.
        """
        # Import py2app for its side-effect of registering the setuptools
        # command.
        assert __import__("py2app") is not None
        sparklePlist: Mapping[str, str] = (
            {} if self.sparkleData is None else self.sparkleData.plist()
        )
        sparkleFrameworks = (
            []
            if self.sparkleData is None
            else [str(self.sparkleData.sparkleFramework.frameworkPath)]
        )
        # resolving a virtualenv gives the actualenv
        pyVersionDir = Path(sys.executable).resolve().parent.parent

        # Tcl/Tk frameworks distributed with Python3.13+ need to be excluded.
        frameworksDir = pyVersionDir / "Frameworks"
        dylibExcludes: list[Path] = []
        if frameworksDir.is_dir():
            dylibExcludes.extend(frameworksDir.iterdir())
        infoPList = {
            "LSUIElement": not self.dockIconAtStart,
            "CFBundleIdentifier": self.bundleID,
            "CFBundleName": self.bundleName,
            # py2app probably doesn't require this any more most of the
            # time, but it doesn't hurt.
            "NSRequiresAquaSystemAppearance": False,
            **sparklePlist,
        }
        return {
            "data_files": [str(f) for f in self.dataFiles],
            "options": {
                "py2app": {
                    "plist": infoPList,
                    "iconfile": str(self.icnsFile),
                    "app": [str(self.mainPythonScript)],
                    "frameworks": [
                        *sparkleFrameworks,
                        *self.otherFrameworks,
                    ],
                    "excludes": [
                        # Excluding setuptools is a workaround for a problem in
                        # py2app -
                        # https://github.com/ronaldoussoren/py2app/issues/531 -
                        # and despite a couple of spuriously declared
                        # transitive dependencies on it
                        # (https://github.com/zopefoundation/zope.interface/issues/339,
                        # https://github.com/twisted/incremental/issues/141) we
                        # don't actually need it
                        "setuptools",
                    ],
                    "dylib_excludes": [str(each) for each in dylibExcludes],
                }
            },
        }
