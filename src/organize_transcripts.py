"""Organize flat transcript files into run subfolders."""

from __future__ import annotations

import click

from src.transcript_utils import organize_transcripts_dir


@click.command()
def cli() -> None:
    """Organize transcripts/ by run folder (live/, meta/, whisper/)."""
    count = organize_transcripts_dir()
    click.echo(f"Organized {count} call(s) into run folders.")


if __name__ == "__main__":
    cli()
