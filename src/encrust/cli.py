from functools import wraps
from getpass import getpass
from json import load
from os.path import expanduser
from typing import Any, Awaitable, Callable, Concatenate, Coroutine, Generator, ParamSpec, TypeVar

import click

from ._build import AppBuilder
from ._spawnutil import c
from twisted.internet.defer import Deferred
from twisted.internet.task import react


P = ParamSpec("P")
R = TypeVar("R")


async def configuredBuilder() -> AppBuilder:
    """
    Make an AppBuilder out of the local configuration.
    """
    with open(expanduser("~/.encrust.json")) as f:
        obj = load(f)
    lines = await c.python("setup.py", "--name", "--version")
    name, version = lines.output.decode("utf-8").strip().split("\n")
    return AppBuilder(
        name=name,
        version=version,
        identityHash=obj["identity"],
        notarizeProfile=obj["profile"],
        appleID=obj["appleID"],
        teamID=obj["teamID"],
    )


def reactorized(
    c: Callable[
        Concatenate[Any, P],
        Coroutine[Deferred[object], Any, object]
        | Generator[Deferred[object], Any, object],
    ]
) -> Callable[P, None]:
    """ """

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
def sign() -> None:
    """
    Locally code-sign your appliation.
    """


@main.command()
def notarize() -> None:
    """
    Submit your application to Apple for notarization and then staple it
    locally.
    """


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
def build() -> None:
    """
    Build the application.
    """


@main.command()
@reactorized
async def auth(reactor: Any) -> None:
    """
    Authenticate to the notarization service with an app-specific password from
    https://appleid.apple.com/account/manage
    """
    builder = await configuredBuilder()
    newpw = getpass(
        f"Paste App-Specific Password for {builder.appleID} and hit enter: "
    )
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
    TODO: this tool should walk you through configuration. For now:
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
    9. `encrust auth`
    """
    )
