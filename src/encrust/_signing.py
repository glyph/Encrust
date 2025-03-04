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


MACH_O_MAGIC = {
    b"\xca\xfe\xba\xbe",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xbe\xba\xfe\xca",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
}


def hasMachOMagic(p: FilePath[str]) -> bool:
    with p.open("r") as f:
        magic = f.read(4)
        return magic in MACH_O_MAGIC


def signablePathsIn(topPath: FilePath[str]) -> Iterable[FilePath[str]]:
    """
    What files need to be individually code-signed within a given bundle?
    """
    built = []
    for p in topPath.walk(lambda subp: (not subp.islink() and subp.isdir())):
        if p.islink():
            continue
        ext = p.splitext()[-1]
        if p.isfile():
            if ext == "":
                if hasMachOMagic(p):
                    built.append(p)
            if ext in {".so", ".dylib", ".a"}:
                built.append(p)
        if p.isdir():
            if ext in {".framework", ".app", ".xpc"}:
                built.append(p)
    return reversed(built)


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
        "--wait",
    )
    await c.xcrun("stapler", "staple", applicationPath.path)
