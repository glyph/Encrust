from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from twisted.internet.defer import Deferred
from twisted.python.filepath import FilePath

from ._spawnutil import c, parallel


@dataclass
class CodeSigner:
    bundle: FilePath[str]
    codesigningIdentity: str
    entitlements: FilePath[str]
    progress: dict[FilePath[str], Deferred[None]] = field(default_factory=dict)

    async def sign(self) -> None:
        active = 0
        async def signOneFile(fileToSign: FilePath[str]) -> None:
            """
            Code sign a single file.
            """
            nonlocal active
            fileStr = fileToSign.path
            entitlementsStr = self.entitlements.path
            print(f"code signing (|| {active}/{len(self.progress)}) {fileToSign}", flush=True)
            allChildren = []
            for eachMaybeChild in self.progress:
                if fileToSign in eachMaybeChild.parents():
                    allChildren.append((eachMaybeChild, self.progress[eachMaybeChild]))
            self.progress[fileToSign] = Deferred()
            for pn, toAwait in allChildren:
                print(f"waiting for {pn.path!r}…")
                await toAwait
                print(f"done waiting for {pn.path!r}!")
            try:
                active += 1
                await c.codesign(
                    "--sign",
                    self.codesigningIdentity,
                    "--entitlements",
                    entitlementsStr,
                    "--force",
                    "--options",
                    "runtime",
                    fileStr,
                )
            finally:
                self.progress.pop(fileToSign).callback(None)
                active -= 1
            print(f"finished signing (|| {active}/{len(self.progress)}) {fileToSign}", flush=True)

        async for signResult in parallel(
            (signOneFile(p) for p in signablePathsIn(self.bundle))
        ):
            pass


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
