from __future__ import annotations


from twisted.python.filepath import FilePath

from ._spawnutil import c


async def createZipFile(zipFile: FilePath, directoryToZip: FilePath) -> None:
    zipPath = zipFile.asTextMode().path
    dirPath = directoryToZip.asTextMode()
    await c.ditto(
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
        dirPath.basename(),
        zipPath,
        workingDirectory=dirPath.dirname(),
    )
