from pathlib import Path

import click


@click.group()
def main() -> None:
    """Seanchaí: Diameter specifications as reviewable `.dad` files."""


@main.command()
@click.argument("docx", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--pdf",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Matching ETSI PDF rendering; attaches `; Page:` directives"
    " from its bookmark outline. Must be the exact same version"
    " as the docx.",
)
@click.option("--link", help="ETSI PDF URL for the file's `; Link:` header.")
@click.option(
    "--patches",
    type=click.Path(file_okay=False, exists=True, path_type=Path),
    help="Directory with input-patch TOML files (default: ./patches if present).",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output .dad path (default: stdout).",
)
def extract(
    docx: Path,
    pdf: Path | None,
    link: str | None,
    patches: Path | None,
    output: Path | None,
) -> None:
    """Extract a canonical `.dad` file from a 3GPP specification docx."""
    from .dad import formatter
    from .extractor import tgpp_docx

    if patches is None and Path("patches").is_dir():
        patches = Path("patches")
    warnings: list[str] = []
    spec = tgpp_docx.extract(docx, link=link, warnings=warnings, patches_dir=patches)
    if pdf is not None:
        spec = tgpp_docx.attach_pages(spec, pdf, warnings=warnings)
    for warning in warnings:
        click.echo(f"warning: {warning}", err=True)
    text = formatter.format(spec)
    if output is None:
        click.echo(text, nl=False)
    else:
        output.write_text(text)
        click.echo(f"wrote {output} ({len(spec.sections)} sections)", err=True)
