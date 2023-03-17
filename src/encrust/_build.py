"""
Future work:

- integrate cocoapods
"""
from __future__ import annotations

from dataclasses import dataclass

from twisted.python.filepath import FilePath
from ._zip import createZipFile
from ._spawnutil import c, parallel
from ._signing import signOneFile, signablePathsIn, notarize





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
    entitlementsPath: FilePath[str]

    async def releaseWorkflow(self) -> None:
        """
        Execute the release end to end; build, sign, archive, notarize, staple.
        """
        await self.build()
        await self.signApp()
        await self.notarizeApp()

    def archivePath(self, variant: str) -> FilePath[str]:
        """
        The path where we should archive our zip file.
        """
        return FilePath("dist").child(f"{self.name}.{variant}.app.zip")

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

    async def authenticateForSigning(self) -> None:
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
        await notarize(
            appleID=self.appleID,
            teamID=self.teamID,
            archivePath=await self.archiveApp("signed"),
            applicationPath=self.originalAppPath(),
            notarizeProfile=self.notarizeProfile,
        )
