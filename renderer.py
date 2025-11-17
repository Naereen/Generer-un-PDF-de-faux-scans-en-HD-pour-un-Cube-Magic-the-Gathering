#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import subprocess
import os
from utils import slug
from cache import ensure_dir


def download_art(card_json, cache, face_idx=0):
    if "image_uris" in card_json:
        img_url = (card_json["image_uris"].get("png") or
                   card_json["image_uris"].get("art_crop"))
    else:
        img_url = card_json["card_faces"][face_idx]["image_uris"]["png"]

    filename = f"{card_json['id']}_{face_idx}.png"
    cached = cache.load_binary("arts", filename)
    if cached:
        return cached

    import requests
    r = requests.get(img_url)
    r.raise_for_status()
    path = cache.save_binary("arts", filename, r.content)
    return path


def render_card_image(card_json, output, cache, force=False):
    """
    Retourne une liste de chemins d’images (recto, recto|verso).
    """
    ensure_dir(output)

    faces = []
    if "card_faces" in card_json:
        for i, face in enumerate(card_json["card_faces"]):
            faces.append(face)
    else:
        faces.append(card_json)

    out_paths = []

    for idx, face in enumerate(faces):
        name = face.get("printed_name") or face.get("name")
        mana = face.get("mana_cost", "")
        type_line = face.get("printed_type_line") or face.get("type_line", "")
        text = face.get("printed_text") or face.get("oracle_text", "")

        art = download_art(card_json, cache, idx)

        out_name = f"{slug(name)}_{idx}.png"
        out_path = os.path.join(output, out_name)

        # caching
        if not force:
            cached = cache.load_binary("renders", out_name)
            if cached:
                out_paths.append(out_path)
                continue

        cmd = [
            "mtgrender", "render",
            "--name", name,
            "--mana-cost", mana,
            "--type-line", type_line,
            "--oracle-text", text,
            "--art", art,
            "--output", out_path,
        ]
        subprocess.run(cmd, check=True)

        cache.save_file_copy("renders", out_name, out_path)
        out_paths.append(out_path)

    return out_paths
