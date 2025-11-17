#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import requests
import os
import json


def fetch_card_data(scry_id, cache):
    """
    Retourne dict Scryfall en FR, gère DFC, cache JSON.
    """
    cached = cache.load_json("cards", f"{scry_id}.json")
    if cached:
        return cached

    url = f"https://api.scryfall.com/cards/{scry_id}?lang=fr"
    resp = requests.get(url)
    if resp.status_code == 404:
        resp = requests.get(f"https://api.scryfall.com/cards/{scry_id}")

    resp.raise_for_status()
    data = resp.json()

    cache.save_json("cards", f"{scry_id}.json", data)
    return data
