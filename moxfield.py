#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import requests


def fetch_moxfield_deck(url: str):
    deck_id = url.rstrip("/").split("/")[-1]
    api_url = f"https://api2.moxfield.com/v2/decks/all/{deck_id}"

    resp = requests.get(api_url)
    resp.raise_for_status()
    return resp.json()
