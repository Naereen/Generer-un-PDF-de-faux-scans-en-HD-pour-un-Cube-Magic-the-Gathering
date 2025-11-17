#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import click
from moxfield import fetch_moxfield_deck
from scryfall import fetch_card_data
from renderer import render_card_image
from pdfgen import generate_pdf
from cache import CacheManager
from utils import slug


@click.group()
def cli():
    pass


@cli.command()
@click.argument("deck_url")
@click.option("--output", "-o", default="output", help="Dossier de sortie")
@click.option("--no-cache", is_flag=True, help="Ne lit pas le cache")
@click.option("--refresh", is_flag=True, help="Supprime cache JSON + arts")
@click.option("--clean", is_flag=True, help="Supprime tout le cache")
@click.option("--force-rerender", is_flag=True, help="Rendu mtgrender forcé")
@click.option("--no-pdf", is_flag=True, help="Ne génère pas le PDF")
@click.option("--only-pdf", is_flag=True, help="Génère uniquement le PDF")
def render(deck_url, output, no_cache, refresh, clean, force_rerender, no_pdf, only_pdf):

    cache = CacheManager(no_cache=no_cache, refresh=refresh, clean=clean)

    deck = fetch_moxfield_deck(deck_url)
    deck_name = slug(deck["name"])

    cards = deck["mainboard"]

    images = []

    if not only_pdf:
        for card_name, entry in cards.items():
            count = entry["quantity"]
            scry_id = entry["card"]["scryfall_id"]

            for i in range(count):
                data = fetch_card_data(scry_id, cache=cache)
                rendered_paths = render_card_image(
                    data,
                    output,
                    cache=cache,
                    force=force_rerender
                )
                images.extend(rendered_paths)

    if not no_pdf:
        pdf_path = f"{output}/{deck_name}.pdf"
        generate_pdf(images, pdf_path)

        click.echo(f"PDF généré : {pdf_path}")


if __name__ == "__main__":
    cli()
