from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from os import environ
from typing import (
    AsyncIterable,
    Awaitable,
    Coroutine,
    Deque,
    Iterable,
    Mapping,
    Sequence,
)


from twisted.internet.defer import Deferred, DeferredSemaphore
from twisted.internet.error import ProcessDone, ProcessTerminated
from twisted.internet.interfaces import IReactorProcess
from twisted.internet.protocol import ProcessProtocol
from twisted.python.failure import Failure
from twisted.python.procutils import which

from ._type import T, R


@dataclass
class ProcessResult:
    """
    The result of running a process to completion.
    """

    status: int
    output: bytes
    invocation: Invocation

    def check(self) -> None:
        """
        make sure that this process didn't exit with error
        """
        if self.status != 0:
            raise RuntimeError(
                f"process {self.invocation.executable} {self.invocation.argv} "
                f"exited with error {self.status}\n"
                f"{self.output.decode('utf-8', 'replace')}"
            )


@dataclass
class InvocationProcessProtocol(ProcessProtocol):
    def __init__(self, invocation: Invocation, quiet: bool) -> None:
        super().__init__()
        self.invocation = invocation
        self.d = Deferred[int]()
        self.quiet = quiet
        self.output = b""
        self.errors = b""

    def show(self, data: bytes) -> None:
        if not self.quiet:
            print(
                f"{self.invocation.executable} {' '.join(self.invocation.argv)}:",
                data.decode("utf-8", "replace").rstrip("\n"),
            )

    def outReceived(self, outData: bytes) -> None:
        self.output += outData
        self.show(outData)

    def errReceived(self, errData: bytes) -> None:
        self.errors += errData
        self.show(errData)

    def processEnded(self, reason: Failure) -> None:
        pd: ProcessDone | ProcessTerminated = reason.value
        self.d.callback(pd.exitCode)


@dataclass
class Invocation:
    """
    A full command-line to be invoked.
    """

    executable: str
    argv: Sequence[str]

    async def __call__(
        self,
        *,
        env: Mapping[str, str] = environ,
        quiet: bool = False,
        workingDirectory: str | None = None,
    ) -> ProcessResult:
        from twisted.internet import reactor

        ipp = InvocationProcessProtocol(self, quiet)
        IReactorProcess(reactor).spawnProcess(
            ipp,
            self.executable,
            [self.executable, *self.argv],
            environ,
            workingDirectory,
        )
        value = await ipp.d
        if value != 0:
            raise RuntimeError(
                f"{self.executable} {self.argv} exited with error {value}"
            )
        return ProcessResult(value, ipp.output, self)


@dataclass
class Command:
    """
    A command is a reference to a potential executable on $PATH that can be
    run.
    """

    name: str

    def __getitem__(self, argv: str | tuple[str, ...]) -> Invocation:
        """ """
        return Invocation(which(self.name)[0], argv)

    async def __call__(
        self,
        *args: str,
        env: Mapping[str, str] = environ,
        quiet: bool = False,
        workingDirectory: str | None = None,
    ) -> ProcessResult:
        """
        Immedately run.
        """
        return await self[args](env=env, quiet=quiet, workingDirectory=workingDirectory)


@dataclass
class SyntaxSugar:
    """
    Syntax sugar for running subprocesses.

    Use like::

        await c.ls()
        await c["docker-compose"]("--help")

    """

    def __getitem__(self, name) -> Command:
        """ """
        return Command(name)

    def __getattr__(self, name) -> Command:
        """ """
        return Command(name)


# from twisted.internet import reactor
c = SyntaxSugar()


async def parallel(
    work: Iterable[Coroutine[Deferred[T], T, R]], parallelism: int = 18
) -> AsyncIterable[R]:
    """
    Perform the given work with a limited level of parallelism.
    """
    sem = DeferredSemaphore(parallelism)
    values: Deque[R] = deque()

    async def saveAndRelease(coro: Awaitable[R]) -> None:
        try:
            values.append(await coro)
        finally:
            sem.release()

    async def drain() -> AsyncIterable[R]:
        await sem.acquire()
        while values:
            yield values.popleft()

    for w in work:
        async for each in drain():
            yield each
        Deferred.fromCoroutine(saveAndRelease(w))

    for x in range(parallelism):
        async for each in drain():
            yield each
