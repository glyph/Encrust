from __future__ import annotations

from typing import Iterable

from twisted.python.filepath import FilePath

from ._spawnutil import c


async def signOneFile(
    fileToSign: FilePath[str],
    codesigningIdentity: str,
    entitlements: FilePath[str],
) -> None:
    """
    Code sign a single file.
    """
    fileStr = fileToSign.path
    entitlementsStr = entitlements.path
    print("✓", end="", flush=True)
    await c.codesign(
        "--sign",
        codesigningIdentity,
        "--entitlements",
        entitlementsStr,
        "--force",
        "--options",
        "runtime",
        fileStr,
    )


def signablePathsIn(topPath: FilePath[str]) -> Iterable[FilePath[str]]:
    """
    What files need to be individually code-signed within a given bundle?
    """
    for p in topPath.walk():
        ext = p.splitext()[-1]
        if ext in {".so", ".dylib", ".framework", ".a"}:
            yield p
        elif p.basename() == 'python' and p.parent().basename() == "MacOS":
            yield p


async def notarize(
    *,
    archivePath: FilePath[str],
    applicationPath: FilePath[str],
    appleID: str,
    teamID: str,
    notarizeProfile: str,
) -> None:
    """
    Submit the signed bundle for notarization, wait for success, then notarize
    it.
    """
    await c.xcrun(
        "notarytool",
        "submit",
        archivePath.path,
        f"--apple-id={appleID}",
        f"--team-id={teamID}",
        f"--keychain-profile={notarizeProfile}",
        f"--wait",
    )
    await c.xcrun("stapler", "staple", applicationPath.path)
