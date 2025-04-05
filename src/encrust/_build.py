"""
Future work:

- integrate cocoapods
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from json import load
from os.path import abspath, expanduser
from typing import Iterable

from twisted.python.filepath import FilePath
from twisted.python.modules import getModule

from ._architecture import fixArchitectures, validateArchitectures
from ._signing import CodeSigner, notarize, signablePathsIn
from ._spawnutil import c
from ._zip import createZipFile


@dataclass
class AppSigner:
    notarizeProfile: str
    appleID: str
    teamID: str
    identityHash: str
    entitlementsPath: FilePath[str] = getModule(__name__).filePath.sibling(
        "required-python-entitlements.plist"
    )


@dataclass
class AppBuilder:
    """
    A builder for a particular application
    """

    name: str
    version: str
    _signer: AppSigner | None = None

    async def signingConfiguration(self) -> AppSigner:
        """
        Load the global signing configuration.
        """
        if self._signer is None:
            with open(expanduser("~/.encrust.json")) as f:
                obj = load(f)
            self._signer = AppSigner(
                identityHash=obj["identity"],
                notarizeProfile=obj["profile"],
                appleID=obj["appleID"],
                teamID=obj["teamID"],
            )
        return self._signer

    async def release(self) -> None:
        """
        Execute the release end to end; build, sign, archive, notarize, staple.
        """
        await self.fattenEnvironment()
        await self.build()
        archOK = await validateArchitectures([self.originalAppPath()], True)
        if not archOK:
            raise RuntimeError()
        await self.signApp()
        await self.notarizeApp()

    async def fattenEnvironment(self) -> None:
        """
        Ensure the current virtualenv has all universal2 "fat" binaries.
        """
        pathEntries = [FilePath(each) for each in sys.path if each]
        needsFattening = not await validateArchitectures(pathEntries)
        if not needsFattening:
            print("already ok")
            return
        await fixArchitectures()
        stillNeedsFattening = not await validateArchitectures(pathEntries, True)
        if stillNeedsFattening:
            raise RuntimeError(
                "single-architecture binaries still exist after fattening: {stillNeedsFattening}"
            )
        print("all relevant binaries now universal2")

    def archivePath(self, variant: str) -> FilePath[str]:
        """
        The path where we should archive our zip file.
        """
        return FilePath("dist").child(f"{self.name}-{self.version}.{variant}.app.zip")

    async def archiveApp(self, variant: str) -> FilePath[str]:
        """ """
        archivedAt = self.archivePath(variant)
        await createZipFile(archivedAt, self.originalAppPath())
        return archivedAt

    async def build(self, *options: str) -> None:
        """
        Invoke py2app to build a copy of the application, with the given py2app
        options.
        """
        await c.python(
            "-m",
            "encrust._dosetup",
            "py2app",
            *options,
            workingDirectory=abspath("."),
        )

    async def authenticateForSigning(self, password: str) -> None:
        """
        Prompt the user to authenticate for code-signing and notarization.
        """
        sign = await self.signingConfiguration()
        await c.xcrun(
            "notarytool",
            "store-credentials",
            sign.notarizeProfile,
            "--apple-id",
            sign.appleID,
            "--team-id",
            sign.teamID,
            "--password",
            password,
        )

    def originalAppPath(self) -> FilePath[str]:
        """
        A L{FilePath} pointing at the application (prior to notarization).
        """
        return FilePath("./dist").child(self.name + ".app")

    def signablePaths(self) -> Iterable[FilePath]:
        return signablePathsIn(self.originalAppPath())

    async def signApp(self) -> None:
        """
        Find all binary files which need to be signed within the bundle and run
        C{codesign} to sign them.
        """
        sign = await self.signingConfiguration()
        signer = CodeSigner(
            self.originalAppPath(),
            sign.identityHash,
            sign.entitlementsPath,
        )
        await signer.sign()

    async def notarizeApp(self) -> None:
        """
        Submit the built application to Apple for notarization and wait until we
        have seen a response.
        """
        sign = await self.signingConfiguration()
        preReleasePath = await self.archiveApp("for-notarizing")
        await notarize(
            appleID=sign.appleID,
            teamID=sign.teamID,
            archivePath=preReleasePath,
            applicationPath=self.originalAppPath(),
            notarizeProfile=sign.notarizeProfile,
        )
        await self.archiveApp("release")
        preReleasePath.remove()
