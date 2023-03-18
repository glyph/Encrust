"""
Future work:

- integrate cocoapods
"""
from __future__ import annotations
import sys

from dataclasses import dataclass

from twisted.python.filepath import FilePath
from twisted.python.modules import getModule

from ._signing import notarize, signOneFile, signablePathsIn
from ._architecture import validateArchitectures, fixArchitectures
from ._spawnutil import c, parallel
from ._zip import createZipFile


@dataclass
class AppBuilder:
    """
    A builder for a particular application
    """

    name: str
    version: str
    notarizeProfile: str
    appleID: str
    teamID: str
    identityHash: str
    entitlementsPath: FilePath[str] = getModule(__name__).filePath.sibling(
        "required-python-entitlements.plist"
    )

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
                "single-architecture binaries still exist after fattening"
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

    async def build(self) -> None:
        """
        Just run py2app.
        """
        await c.python("setup.py", "py2app")

    async def authenticateForSigning(self, password: str) -> None:
        """
        Prompt the user to authenticate for code-signing and notarization.
        """
        await c.xcrun(
            "notarytool",
            "store-credentials",
            self.notarizeProfile,
            "--apple-id",
            self.appleID,
            "--team-id",
            self.teamID,
            "--password",
            password,
        )

    def originalAppPath(self) -> FilePath[str]:
        """
        A L{FilePath} pointing at the application (prior to notarization).
        """
        return FilePath("./dist").child(self.name + ".app")

    async def signApp(self) -> None:
        """
        Find all binary files which need to be signed within the bundle and run
        C{codesign} to sign them.
        """
        top = self.originalAppPath()
        async for signResult in parallel(
            (
                signOneFile(p, self.identityHash, self.entitlementsPath)
                for p in signablePathsIn(top)
            )
        ):
            pass
        await signOneFile(top, self.identityHash, self.entitlementsPath)

    async def notarizeApp(self) -> None:
        """
        Submit the built application to Apple for notarization and wait until we
        have seen a response.
        """
        preReleasePath = await self.archiveApp("for-notarizing")
        await notarize(
            appleID=self.appleID,
            teamID=self.teamID,
            archivePath=preReleasePath,
            applicationPath=self.originalAppPath(),
            notarizeProfile=self.notarizeProfile,
        )
        await self.archiveApp("release")
        preReleasePath.remove()
