import sys
from functools import wraps
from getpass import getpass
from os import environ
from os.path import abspath
from typing import Any, Callable, Concatenate, Coroutine, Generator, ParamSpec, TypeVar

import click
from twisted.internet.defer import Deferred
from twisted.internet.task import react
from twisted.python.failure import Failure

from ._build import AppBuilder
from ._spawnutil import c
from .api import AppDescription

P = ParamSpec("P")
R = TypeVar("R")


async def configuredBuilder() -> AppBuilder:
    """
    Make an AppBuilder out of the local configuration.
    """
    lines = await c.python(
        "-m",
        "encrust._dosetup",
        "--name",
        "--version",
        workingDirectory=abspath("."),
    )
    name, version = lines.output.decode("utf-8").strip().split("\n")
    name = environ.get("ENCRUST_APP_NAME", name)
    version = environ.get("ENCRUST_APP_VERSION", version)
    return AppBuilder(name=name, version=version)


def reactorized(
    c: Callable[
        Concatenate[Any, P],
        Coroutine[Deferred[object], Any, object]
        | Generator[Deferred[object], Any, object],
    ],
) -> Callable[P, None]:
    """
    Wrap an async twisted function for click.
    """

    @wraps(c)
    def forclick(*a, **kw) -> None:
        def r(reactor: Any) -> Deferred[object]:
            async def ar():
                try:
                    await c(reactor, *a, **kw)
                except Exception:
                    print(Failure().getTraceback())

            return Deferred.fromCoroutine(ar())

        react(r, [])

    return forclick


@click.group()
def main() -> None:
    """
    Utility for building, signing, and notarizing macOS applications.
    """


@main.command()
@reactorized
async def signable(reactor: Any) -> None:
    """
    (Debugging): print a list of every signable path in an already-built bundle.
    """
    builder = await configuredBuilder()
    for p in builder.signablePaths():
        print(p.path)


@main.command()
@reactorized
async def sign(reactor: Any) -> None:
    """
    (Debugging): Just locally codesign (and do not notarize) an already-built app.
    """
    builder = await configuredBuilder()
    await builder.signApp()


@main.command()
@reactorized
async def fatten(reactor: Any) -> None:
    """
    Ensure that all locally installed shared objects are fat binaries (i.e.
    universal2 wheels).
    """
    builder = await configuredBuilder()
    await builder.fattenEnvironment()


@main.command()
@reactorized
async def build(reactor: Any) -> None:
    """
    Build the application.
    """
    builder = await configuredBuilder()
    await builder.build()
    await builder.signApp()


@main.command()
@reactorized
async def devalias(reactor: Any) -> None:
    """
    Build an app bundle that uses a symlink into the development copy of the
    source code, suitable only for local development, but a lot faster than
    rebuilding all the time.

    @see: U{py2app alias mode
        <https://py2app.readthedocs.io/en/latest/tutorial.html#development-with-alias-mode>}
    """
    builder = await configuredBuilder()
    await builder.build("--alias")


@main.command()
@reactorized
async def release(reactor: Any) -> None:
    """
    Build the application.
    """
    builder = await configuredBuilder()
    await builder.release()


def loadDescription() -> AppDescription:
    """
    Load the description of the project from C{encrust_setup.py}.
    """
    sys.path.append(".")
    import encrust_setup  # type:ignore[import-not-found]

    desc = encrust_setup.description
    return desc


@main.command()
@reactorized
async def getsparkle(reactor: Any) -> None:
    """
    Download the Sparkle framework used by the current project.
    """
    # TODO: should probably use something like Cocoapods to actually fetch
    # frameworks so that this generalizes a bit.  But I would have to learn how
    # Cocoapods work for that.
    description = loadDescription()
    if description.sparkleData is None:
        print("Sparkle not specified, not downloading.")
        sys.exit(1)

    await description.sparkleData.sparkleFramework.download()


@main.command()
@reactorized
async def appcastify(reactor: Any) -> None:
    """
    Update, sign, and deploy the Sparkle appcast for the current application.

    Note that this currently must be manually done *after* `encrust release`,
    but we should probably integrate it into that process.
    """
    description = loadDescription()
    if description.sparkleData is None:
        print("Sparkle not specified, not generating appcast.")
        sys.exit(1)
    await description.sparkleData.deploy()


@main.command()
@reactorized
async def auth(reactor: Any) -> None:
    """
    Authenticate to the notarization service with an app-specific password from
    https://appleid.apple.com/account/manage
    """
    builder = await configuredBuilder()
    sign = await builder.signingConfiguration()
    newpw = getpass(f"Paste App-Specific Password for {sign.appleID} and hit enter: ")
    await builder.authenticateForSigning(newpw)
    print("Authenticated!")


@main.command()
@reactorized
async def configure(reactor: Any) -> None:
    """
    Configure this tool.
    """
    print(
        """
    TODO: this tool should walk you through configuration.

    For now:
    0. First, set up a Python project built using `py2app`.
        a. make a virtualenv
        b. `pip install` your dependencies
        c. `pip install encrust`

    1. enroll in the Apple Developer program at https://developer.apple.com/account
    2. download Xcode.app from https://apps.apple.com/us/app/xcode/id497799835?mt=12
    3. launch Xcode,
        a. open Preferences -> Accounts
        b. hit '+' to log in to the Apple ID you enrolled in
           the developer program with
        c. click "manage certificates"
        d. click "+"
        e. click "Developer ID Application"
    4. run `security find-identity -v -p codesigning`
    5. look for a "Developer ID Application" certificate in the list
    6. edit ~/.encrust.json to contain an object like this:

        {
            "identity": /* the big hex ID from find-identity output */,
            "teamID": /* the thing in parentheses in find-identity output */,
            "appleID": /* the email address associated with your apple developer account */,
            "profile": /* an arbitrary string you've selected */
        }
    7. go to https://appleid.apple.com/account/manage and log in
    8. click "App-Specific Passwords"
    9. run `encrust auth` and paste the app password before closing the window
    10. run `encrust release`
    11. upload dist/<YourApp>-<YourVersion>.release.app.zip somewhere on the web.
    """
    )
