import click


@click.group()
def main() -> None:
    print("hello, world!")


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
def fatten() -> None:
    """
    Ensure that all locally installed shared objects are fat binaries (i.e.
    universal2 wheels).
    """


@main.command()
def build() -> None:
    """
    Build the application.
    """


@main.command()
def configure() -> None:
    """
    Configure this tool.
    """

