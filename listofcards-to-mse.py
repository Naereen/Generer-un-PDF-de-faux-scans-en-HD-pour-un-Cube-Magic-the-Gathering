#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
listofcards-to-mse.py

Script Python autonome (sans Ruby) qui :
- lit un fichier texte de type "Moxfield" (liste de cartes),
- télécharge les données de cartes via l'API Scryfall (en essayant d'utiliser la version FR si elle existe),
- génère un set .mse-set (zip) pour Magic Set Editor (MSE), jeu "magic", template M15.

Format d'entrée attendu (exemple) :
    1 Anafenza, the Foremost (KTK) 163 *F*
    1 Anguished Unmaking (LTC) 265

Les champs entre parenthèses (code d'édition), numéro de collector et flags (*F*, etc.)
sont utilisés pour cibler set/collector, seul le nom est utilisé si ces infos manquent.

Limitations :
- Ne gère que le jeu "magic" (standard),
- Ne gère pas Planechase, Archenemy, Vanguard, etc.,
- Ne gère pas les tokens,
- Ne gère pas les cartes "uncards" (silver border) sauf option explicite.

Dépendances Python :
    pip install pillow piexif regex requests
"""

import sys
import argparse
import datetime
import enum
import io
import os
import zipfile
import time
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set

import PIL.Image
import piexif
import regex
import requests

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SCRYFALL_API_NAMED = "https://api.scryfall.com/cards/named"
SCRYFALL_API_SEARCH = "https://api.scryfall.com/cards/search"
SCRYFALL_RATE_LIMIT_MS = 100  # recommandé par Scryfall

SCRYFALL_REQUEST_TIMEOUT = datetime.datetime.now(datetime.timezone.utc)

BASIC_LAND_TYPES = {
    "Plains": "W",
    "Island": "U",
    "Swamp": "B",
    "Mountain": "R",
    "Forest": "G",
}

COLOR_ABBREVIATIONS = {
    "W": "White",
    "U": "Blue",
    "B": "Black",
    "R": "Red",
    "G": "Green",
}

BLACK_BORDERED_UNCARDS = {
    "1996 World Champion",
    "Fraternal Exaltation",
    "Proposal",
    "Robot Chicken",
    "Shichifukujin Dragon",
    "Splendid Genesis",
}

IMAGE_FILE_EXTS = [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]


class UncardError(ValueError):
    """Erreur levée pour les Un-cards si non autorisées."""
    pass


# ---------------------------------------------------------------------------
# Utilitaires Scryfall
# ---------------------------------------------------------------------------

def scryfall_request(url: str, *, params: Optional[Dict] = None) -> requests.Response:
    """Appelle Scryfall en respectant un rate-limit simple global."""
    global SCRYFALL_REQUEST_TIMEOUT

    sleep_secs = (SCRYFALL_REQUEST_TIMEOUT - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    if sleep_secs > 0:
        time.sleep(sleep_secs)
    response = requests.get(url, params=params)
    SCRYFALL_REQUEST_TIMEOUT = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        milliseconds=SCRYFALL_RATE_LIMIT_MS
    )
    response.raise_for_status()
    return response


@dataclass
class CardFaceData:
    """Données structurées d'une face de carte, issues de Scryfall."""
    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    power: Optional[str] = None
    toughness: Optional[str] = None
    loyalty: Optional[str] = None


@dataclass
class ScryfallCard:
    """Données structurées d'une carte Scryfall."""
    name: str
    layout: str
    colors: List[str]
    color_identity: List[str]
    type_line: str
    oracle_text: str
    mana_cost: str
    rarity: str
    set: str
    collector_number: str
    artist: Optional[str]
    border_color: str
    image_uris: Optional[Dict[str, str]] = None
    card_faces: List[CardFaceData] = field(default_factory=list)
    all_prints: List[Dict] = field(default_factory=list)  # printings data for min rarity
    lang: str = "en"

    # Informations sur l'impression "demandée" dans la ligne Moxfield
    original_set: Optional[str] = None
    original_collector_number: Optional[str] = None
    original_lang: Optional[str] = None

    # Clé de cache dérivée de la ligne Moxfield
    cache_key: Optional[str] = None


def _build_scryfall_card_from_json(data: Dict) -> ScryfallCard:
    """Construit un ScryfallCard à partir du JSON brut Scryfall, en gérant les MDFC."""
    layout = data.get("layout", "normal")
    card_faces: List[CardFaceData] = []
    if "card_faces" in data:
        for face in data["card_faces"]:
            card_faces.append(
                CardFaceData(
                    name=face.get("name", data.get("name", "")),
                    mana_cost=face.get("mana_cost") or "",
                    type_line=face.get("type_line") or "",
                    oracle_text=face.get("oracle_text") or "",
                    power=face.get("power"),
                    toughness=face.get("toughness"),
                    loyalty=face.get("loyalty"),
                )
            )

    # Pour beaucoup de MDFC, type_line/oracle_text/mana_cost sont sur les faces, pas à la racine.
    type_line = data.get("type_line") or (card_faces[0].type_line if card_faces else "")
    oracle_text = data.get("oracle_text") or (card_faces[0].oracle_text if card_faces else "")
    mana_cost = data.get("mana_cost") or (card_faces[0].mana_cost if card_faces else "")

    # Collecter tous les printings pour le calcul de la rareté min
    prints = []
    if data.get("prints_search_uri"):
        prints_resp = scryfall_request(data["prints_search_uri"])
        prints = prints_resp.json().get("data", [])

    return ScryfallCard(
        name=data["name"],
        layout=data.get("layout", "normal"),
        colors=data.get("colors", []),
        color_identity=data.get("color_identity", []),
        type_line=type_line,
        oracle_text=oracle_text,
        mana_cost=mana_cost,
        rarity=data.get("rarity", "common").capitalize(),
        set=data.get("set", "").upper(),
        collector_number=data.get("collector_number", "") or "",
        artist=data.get("artist"),
        border_color=data.get("border_color", "black"),
        image_uris=data.get("image_uris"),
        card_faces=card_faces,
        all_prints=prints,
        lang=data.get("lang", "en"),
    )


def fetch_card_from_scryfall_raw_by_name(name: str) -> ScryfallCard:
    """Récupère une carte Scryfall par nom (langue par défaut, 'named?exact=')."""
    resp = scryfall_request(SCRYFALL_API_NAMED, params={"exact": name})
    data = resp.json()
    return _build_scryfall_card_from_json(data)


def _search_one_card(query: str) -> Optional[Dict]:
    """Retourne le premier résultat JSON pour une requête de recherche Scryfall (ou None)."""
    resp = scryfall_request(SCRYFALL_API_SEARCH, params={"q": query})
    data = resp.json()
    results = data.get("data", [])
    if not results:
        return None
    return results[0]


def fetch_printing(set_code: Optional[str],
                   collector_number: Optional[str],
                   name: str,
                   preferred_lang: str,
                   cache_key: str) -> ScryfallCard:
    """
    Récupère une carte en préférant :
    1. L'impression set/number en preferred_lang,
    2. Sinon l'impression set/number en anglais,
    3. Sinon une impression FR (toutes éditions) par nom,
    4. Sinon une impression EN par nom,
    5. Sinon named?exact=Nom.
    """
    original_set = set_code.upper() if set_code else None
    original_num = collector_number
    original_lang = preferred_lang

    def make_card_from_data(data: Dict) -> ScryfallCard:
        card = _build_scryfall_card_from_json(data)
        card.original_set = original_set
        card.original_collector_number = original_num
        card.original_lang = original_lang
        card.cache_key = cache_key
        return card

    # 1. Impression exacte set/number en FR puis EN
    if set_code and collector_number:
        set_q = set_code.lower()
        num_q = collector_number

        # FR
        try:
            q = f"set:{set_q} number:{num_q} lang:{preferred_lang}"
            data = _search_one_card(q)
            if data is not None:
                card = make_card_from_data(data)
                card.lang = data.get("lang", preferred_lang)
                return card
        except requests.HTTPError:
            pass

        # EN
        try:
            q = f"set:{set_q} number:{num_q} lang:en"
            data = _search_one_card(q)
            if data is not None:
                card = make_card_from_data(data)
                card.lang = data.get("lang", "en")
                return card
        except requests.HTTPError:
            pass

    # 2. Toute édition FR par nom exact
    try:
        q = f'!"{name}" lang:{preferred_lang}'
        data = _search_one_card(q)
        if data is not None:
            card = make_card_from_data(data)
            card.lang = data.get("lang", preferred_lang)
            return card
    except requests.HTTPError:
        pass

    # 3. Toute édition EN par nom exact
    try:
        q = f'!"{name}" lang:en'
        data = _search_one_card(q)
        if data is not None:
            card = make_card_from_data(data)
            card.lang = data.get("lang", "en")
            return card
    except requests.HTTPError:
        pass

    # 4. Fallback ultime : named?exact=Nom (langue par défaut)
    card = fetch_card_from_scryfall_raw_by_name(name)
    card.original_set = original_set
    card.original_collector_number = original_num
    card.original_lang = original_lang
    card.cache_key = cache_key
    return card


# ---------------------------------------------------------------------------
# Conversion coût de mana / couleurs implicites
# ---------------------------------------------------------------------------

def cost_to_mse(cost: str, *, normalize: bool = False) -> str:
    """Convertit un coût de mana Scryfall en string MSE."""
    def cost_part_to_mse(part: str) -> str:
        basics = "[WUBRG]"
        if regex.fullmatch(basics, part):
            return part
        if part in ("C", "E", "Q", "S", "T", "X"):
            return part
        if part == "P":
            return "phi"
        if part == "CHAOS":
            return "chaos"
        if regex.fullmatch(r"[0-9]+", part):
            return part
        if regex.fullmatch(r"[WUBRG]/[WUBRG]", part):
            return part
        match = regex.fullmatch(r"([WUBRG])/P", part)
        if match:
            return f"H/{match.group(1)}"
        if regex.fullmatch(r"2/[WUBRG]", part):
            return part
        raise ValueError(f"Unknown mana cost part: {{{part}}}")

    if not cost:
        return ""
    if cost[0] != "{" or cost[-1] != "}":
        if "{" not in cost:
            return cost
        raise ValueError("Cost must start with { and end with }")

    parts = cost[1:-1].split("}{")
    if not normalize:
        return "".join(cost_part_to_mse(p) for p in parts)

    result = ""
    remaining = list(parts)

    # X en tête
    for i in reversed(range(len(remaining))):
        if remaining[i] == "X":
            result += cost_part_to_mse("X")
            del remaining[i]

    # Générique
    total_generic = 0
    for i in reversed(range(len(remaining))):
        if regex.fullmatch(r"[0-9]+", remaining[i]):
            g = int(remaining[i])
            if g == 0:
                result += cost_part_to_mse("0")
            total_generic += g
            del remaining[i]
    if total_generic > 0:
        result += cost_part_to_mse(str(total_generic))

    # S, C séparés
    for symbol in ("S", "C"):
        for i in reversed(range(len(remaining))):
            if remaining[i] == symbol:
                result += cost_part_to_mse(symbol)
                del remaining[i]

    def canonical_order(result_list: List[str], symbols: List[str]) -> str:
        counts = [0] * len(symbols)
        for i in reversed(range(len(result_list))):
            for idx, sym in enumerate(symbols):
                if result_list[i] == sym:
                    counts[idx] += 1
                    del result_list[i]
                    break
        return "".join(cost_part_to_mse(symbols[i]) * counts[i] for i in range(len(symbols)))

    # twobrid
    result += canonical_order(remaining, ["2/W", "2/U", "2/B", "2/R", "2/G"])

    # hybrides
    hybrid_order = [
        "W/U", "U/B", "B/R", "R/G", "G/W",
        "W/B", "U/R", "B/G", "R/W", "G/U",
    ]
    for sym in hybrid_order:
        for i in reversed(range(len(remaining))):
            if remaining[i] == sym:
                result += cost_part_to_mse(sym)
                del remaining[i]

    # Phyrexian
    result += canonical_order(remaining, ["W/P", "U/P", "B/P", "R/P", "G/P"])

    # couleurs simples
    result += canonical_order(remaining, ["W", "U", "B", "R", "G"])

    # le reste
    result += "".join(cost_part_to_mse(p) for p in remaining)
    return result


def implicit_colors(cost: str, short: bool = False) -> List[str]:
    """Couleurs implicites à partir du coût."""
    def cost_part_colors(part: str) -> Set[str]:
        basics = "[WUBRG]"
        if regex.fullmatch(basics, part):
            return {COLOR_ABBREVIATIONS[part]}
        if part in ("C", "S", "X") or regex.fullmatch(r"[0-9]+", part):
            return set()
        if regex.fullmatch(r"[WUBRG]/[WUBRG]", part):
            left, right = part.split("/")
            return {COLOR_ABBREVIATIONS[left], COLOR_ABBREVIATIONS[right]}
        match = regex.fullmatch(r"([WUBRG])/P", part)
        if match:
            return {COLOR_ABBREVIATIONS[match.group(1)]}
        match = regex.fullmatch(r"2/([WUBRG])", part)
        if match:
            return {COLOR_ABBREVIATIONS[match.group(1)]}
        return set()

    if not cost:
        return []
    if cost[0] != "{" or cost[-1] != "}":
        if "{" not in cost:
            return []
        raise ValueError("Cost must start with { and end with }")

    colors: Set[str] = set()
    parts = cost[1:-1].split("}{")
    for p in parts:
        colors |= cost_part_colors(p)

    ordered = []
    for color in ("White", "Blue", "Black", "Red", "Green"):
        if color in colors:
            if short:
                ordered.append(
                    {"White": "W", "Blue": "U", "Black": "B", "Red": "R", "Green": "G"}[color]
                )
            else:
                ordered.append(color)
    return ordered


# ---------------------------------------------------------------------------
# Enum de rareté (MSE)
# ---------------------------------------------------------------------------

class OrderedEnum(enum.Enum):
    def __ge__(self, other):
        if self.__class__ is other.__class__:
            return self.value >= other.value
        return NotImplemented

    def __gt__(self, other):
        if self.__class__ is other.__class__:
            return self.value > other.value
        return NotImplemented

    def __le__(self, other):
        if self.__class__ is other.__class__:
            return self.value <= other.value
        return NotImplemented

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented


class Rarity(OrderedEnum):
    BASIC = (0, "basic land")
    COMMON = (1, "common")
    UNCOMMON = (2, "uncommon")
    RARE = (3, "rare")
    MYTHIC = (4, "mythic rare")
    SPECIAL = (5, "special")

    def __init__(self, idx, mse_str):
        self.mse_str = mse_str

    @classmethod
    def from_scryfall_str(cls, rarity_str: str) -> "Rarity":
        mapping = {
            "basic": cls.BASIC,
            "common": cls.COMMON,
            "uncommon": cls.UNCOMMON,
            "rare": cls.RARE,
            "mythic": cls.MYTHIC,
            "special": cls.SPECIAL,
        }
        rarity_str = rarity_str.lower()
        return mapping.get(rarity_str, cls.COMMON)


# ---------------------------------------------------------------------------
# MSEDataFile : structure de données MSE
# ---------------------------------------------------------------------------

class MSEDataFile:
    def __init__(self, data: Optional[Dict] = None):
        self.images: List[str] = []
        self.items: List[Tuple[str, object]] = []
        self.stylesheets: Set[str] = set()
        if data:
            for k, v in data.items():
                self[k] = v

    def __contains__(self, key):
        return any(k == key for k, _ in self.items)

    def __getitem__(self, key):
        result = None
        for k, v in self.items:
            if k == key:
                if result is None:
                    result = v
                else:
                    raise KeyError(f"Multiple values for key {key!r}")
        if result is None:
            raise KeyError(f"No values for key {key!r}")
        return result

    def __setitem__(self, key, value):
        for k, _ in self.items:
            if k == key:
                raise KeyError("Key exists")
        self.add(key, value)

    def __ior__(self, other: "MSEDataFile"):
        for k, v in other.items:
            self[k] = v
        return self

    def __str__(self):
        return self.to_string()

    def add(self, key, value):
        if isinstance(value, dict):
            value = MSEDataFile(value)
        elif value is True:
            value = "true"
        elif value is False:
            value = "false"
        self.items.append((key, value))

    def get(self, key, default=None):
        for k, v in self.items:
            if k == key:
                return v
        return default

    def to_string(self, indent=0) -> str:
        result = ""
        for key, value in self.items:
            result += "\t" * indent
            if isinstance(value, MSEDataFile):
                result += f"{key}:\r\n"
                result += value.to_string(indent=indent + 1)
            else:
                value_str = str(value)
                if "\n" in value_str:
                    result += f"{key}:\r\n"
                    for line in value_str.split("\n"):
                        result += "\t" * (indent + 1)
                        result += f"{line}\r\n"
                else:
                    result += f"{key}: {value}\r\n"
        return result


# ---------------------------------------------------------------------------
# Conversion Scryfall -> MSE card
# ---------------------------------------------------------------------------

def build_image_cache_name(card: ScryfallCard) -> str:
    """
    Construit un nom de fichier stable pour le cache d'images.

    Priorité :
    - cache_key (dérivé de la ligne Moxfield),
    - sinon set/collector/lang,
    - sinon nom de carte.
    """
    if card.cache_key:
        base = f"{card.cache_key}_{card.lang}"
    else:
        base = f"{card.set.lower()}_{card.collector_number or 'no-num'}_{card.lang}"
    return base.replace(":", "").replace('"', "").replace("?", "")


def save_card_art(card: ScryfallCard, images_dir: Optional[str]) -> Tuple[Optional[str], bool, Optional[str]]:
    """Télécharge l'illustration de la carte (art_crop si possible), avec cache."""
    if images_dir is None:
        return None, False, card.artist

    os.makedirs(images_dir, exist_ok=True)

    img_url = None
    if card.image_uris:
        img_url = card.image_uris.get("art_crop") or card.image_uris.get("normal") or card.image_uris.get("large")

    image_filename = f"{build_image_cache_name(card)}.jpg"
    image_path = os.path.join(images_dir, image_filename)

    if os.path.exists(image_path):
        # Utilisation du cache si possible
        try:
            with PIL.Image.open(image_path) as img:
                image_is_vertical = img.size[1] > img.size[0]
            return image_path, image_is_vertical, card.artist
        except Exception:
            # Si le fichier est illisible, on le supprime et on retélécharge
            try:
                os.remove(image_path)
            except OSError:
                pass

    if not img_url:
        return None, False, card.artist

    response = scryfall_request(img_url)
    data = response.content

    with PIL.Image.open(io.BytesIO(data)) as img:
        image_is_vertical = img.size[1] > img.size[0]
        exif = piexif.load(img.info.get("exif", piexif.dump({})))
        artist = card.artist
        if artist:
            exif["0th"][piexif.ImageIFD.Artist] = artist.encode("utf-8")
            if exif.get("thumbnail"):
                exif["1st"][piexif.ImageIFD.Artist] = artist.encode("utf-8")
        img.save(image_path, exif=piexif.dump(exif))
    return image_path, image_is_vertical, card.artist


def build_mse_card(
    card: ScryfallCard,
    set_file: MSEDataFile,
    *,
    images_dir: Optional[str],
    images_to_add: List[str],
    allow_uncards: bool,
    new_wedge_order: bool,
) -> None:
    """Ajoute une carte (ScryfallCard) au MSEDataFile."""

    # Un-cards
    if not allow_uncards:
        if card.border_color == "silver":
            raise UncardError("Un-cards are not supported")
        if card.name in BLACK_BORDERED_UNCARDS:
            raise UncardError("This card is blacklisted and will not be supported")

    # pas de tokens
    if "token" in card.layout:
        raise ValueError("Token cards are not supported")

    result = MSEDataFile()

    # Face principale (pour MDFC / transform : on prend la première face)
    main_face = card.card_faces[0] if card.card_faces else None

    # nom
    result["name"] = card.name

    # coût de mana
    mana_cost = card.mana_cost or (main_face.mana_cost if main_face else "")
    if mana_cost:
        result["casting cost"] = cost_to_mse(mana_cost, normalize=new_wedge_order)

    # image
    image_path, image_is_vertical, artist = save_card_art(card, images_dir)
    if image_path is not None:
        result["image"] = f"image{len(images_to_add) + 1}"
        images_to_add.append(image_path)
    if artist:
        result["illustrator"] = artist

    # note sur l'impression utilisée / demandée
    note_parts = []
    if card.original_set or card.original_collector_number or card.original_lang:
        req_set = card.original_set or card.set
        req_num = card.original_collector_number or card.collector_number or "?"
        req_lang = card.original_lang or "?"
        used_set = card.set
        used_num = card.collector_number or "?"
        used_lang = card.lang

        requested_str = f"{req_set}/{req_num}/{req_lang}"
        used_str = f"{used_set}/{used_num}/{used_lang}"

        if (req_set, req_num, req_lang) == (used_set, used_num, used_lang):
            note_parts.append(f"printing {used_lang}: {used_str}")
        else:
            note_parts.append(f"requested: {requested_str} ; used: {used_str}")
    if note_parts:
        result["note"] = " | ".join(note_parts)

    # couleurs / frame color & indicator (basé sur card.colors)
    frame_color_parts: List[str] = []
    if not card.colors:
        if "Artifact" not in (card.type_line or ""):
            frame_color_parts.append("colorless")
    elif len(card.colors) > 2:
        frame_color_parts.append("multicolor")
    else:
        frame_color_parts += [c.lower() for c in card.colors]

    if "Artifact" in card.type_line:
        frame_color_parts.append("artifact")
    if "Land" in card.type_line:
        frame_color_parts.append("land")

    if "Land" in card.type_line:
        if not card.colors:
            land_colors = [c.lower() for c in could_produce_from_text(card) if c != "Colorless"]
            if len(land_colors) > 2:
                frame_color = "multicolor, land"
            elif len(land_colors) > 0:
                frame_color = ", ".join(land_colors) + ", land"
            else:
                frame_color = "land"
            result["card color"] = frame_color
            result["indicator"] = "colorless"
        else:
            result["card color"] = ", ".join(frame_color_parts)
            result["indicator"] = ", ".join(c.lower() for c in card.colors)
            result["has styling"] = True
            result["styling data"] = {"color indicator dot": "yes"}
    else:
        implicit = implicit_colors(mana_cost)
        if set(card.colors) != set(implicit):
            if not card.colors:
                result["card color"] = ", ".join(
                    c.lower() for c in implicit_colors(mana_cost, short=False)
                ) or ", ".join(frame_color_parts)
            else:
                result["card color"] = ", ".join(frame_color_parts)
                result["indicator"] = ", ".join(c.lower() for c in card.colors)
                result["has styling"] = True
                result["styling data"] = {"color indicator dot": "yes"}
        else:
            if not card.colors and image_is_vertical and not any(
                t in card.type_line for t in ["Artifact", "Land", "Phenomenon", "Plane", "Scheme", "Vanguard"]
            ):
                pass
            if frame_color_parts:
                result["card color"] = ", ".join(frame_color_parts)

    # type line
    type_line = card.type_line or (main_face.type_line if main_face else "")
    super_types: List[str] = []
    types: List[str] = []
    sub_types: List[str] = []

    if "—" in type_line:
        left, right = [p.strip() for p in type_line.split("—", 1)]
        sub_types = right.split(" ")
    else:
        left = type_line

    for part in left.split(" "):
        if part in ("Basic", "Legendary", "Snow", "World", "Ongoing"):
            super_types.append(part)
        elif part:
            types.append(part)

    if super_types:
        result["super type"] = f'<word-list-type>{" ".join(super_types)} {" ".join(types)}</word-list-type>'
    else:
        result["super type"] = f'<word-list-type>{" ".join(types)}</word-list-type>'

    if sub_types:
        if "Creature" in types:
            card_type_for_subtypes = "race"
        elif "Instant" in types or "Sorcery" in types:
            card_type_for_subtypes = "spell"
        else:
            card_type_for_subtypes = types[0].lower() if types else "type"
        result["sub type"] = " ".join(
            f"<word-list-{card_type_for_subtypes}>{st}</word-list-{card_type_for_subtypes}>"
            for st in sub_types
        )

    # rareté : minimal sur tous les printings
    rarity_candidates = [card.rarity] + [p.get("rarity", "").capitalize() for p in card.all_prints]
    rarity_enums = [Rarity.from_scryfall_str(r) for r in rarity_candidates if r]
    rarity_mse = min(rarity_enums).mse_str if rarity_enums else Rarity.COMMON.mse_str
    result["rarity"] = rarity_mse

    # texte de règles (face principale)
    oracle_text = card.oracle_text or (main_face.oracle_text if main_face else "")
    rule_text = build_rule_text(oracle_text, types)
    result["rule text"] = rule_text

    # watermark pour terrains de base vanilla
    if not rule_text.strip() and "Land" in types:
        if len(sub_types) == 1 and sub_types[0] in BASIC_LAND_TYPES:
            subtype = sub_types[0]
            result["watermark"] = f"mana symbol {COLOR_ABBREVIATIONS[BASIC_LAND_TYPES[subtype]].lower()}"
        elif len(sub_types) == 2 and all(st in BASIC_LAND_TYPES for st in sub_types):
            color1, color2 = (BASIC_LAND_TYPES[st] for st in sub_types)
            result["watermark"] = f"colored xander hybrid mana {color1}/{color2}"

    # P/T, loyalty
    if "Creature" in types or "Vehicle" in types:
        pt_power = main_face.power if main_face and main_face.power is not None else None
        pt_toughness = main_face.toughness if main_face and main_face.toughness is not None else None
        if pt_power is not None:
            result["power"] = pt_power
        if pt_toughness is not None:
            result["toughness"] = pt_toughness

    if "Planeswalker" in types:
        loyalty_val = main_face.loyalty if main_face and main_face.loyalty is not None else None
        if loyalty_val is not None:
            result["loyalty"] = loyalty_val

    # stylesheet : base M15
    result["stylesheet"] = "m15"
    set_file.stylesheets.add("m15")

    set_file.add("card", result)


def build_rule_text(oracle_text: str, types: List[str]) -> str:
    """Construit le texte de règles en format MSE (symbole {X}, puces, etc.)."""
    if not oracle_text:
        return ""
    text_out = ""
    lines = oracle_text.replace("‘", "'").replace("’", "'").split("\n")
    for line in lines:
        if not line.strip():
            continue
        if text_out:
            if line.lstrip().startswith("•"):
                text_out += "<soft-line>\n</soft-line>"
            else:
                text_out += "\n"
        words = line.split(" ")
        first = True
        for word in words:
            if not first:
                text_out += " "
            first = False
            parts = word.split("\u2014")
            first_part = True
            for part in parts:
                if not first_part:
                    text_out += "\u2014"
                first_part = False
                m = regex.fullmatch(r'(["\']?)\{(.+?)\}([:.,]?["\']*)', part)
                if m:
                    before = m.group(1) or ""
                    inner = m.group(2)
                    after = m.group(3) or ""
                    text_out += f'{before}<sym>{cost_to_mse("{" + inner + "}")}</sym>{after}'
                elif regex.fullmatch(r"[0-9]+|[XVI]+", part):
                    text_out += f"</sym>{part}<sym>"
                else:
                    text_out += part
    return text_out


def could_produce_from_text(card: ScryfallCard) -> Set[str]:
    """Approximation : types de mana que ce terrain peut produire, basé sur le texte."""
    result: Set[str] = set()

    for basic_land_type, mana_color in BASIC_LAND_TYPES.items():
        if basic_land_type in card.type_line:
            result.add(COLOR_ABBREVIATIONS[mana_color])

    text = card.oracle_text or ""
    match = regex.search(
        r"(add(,?( or)? (\{(?P<types>[CWUBRG])\})+)+)+",
        text,
        regex.IGNORECASE | regex.DOTALL,
    )
    if match:
        for mana_type in match.captures("types"):
            if mana_type == "C":
                result.add("Colorless")
            else:
                result.add(COLOR_ABBREVIATIONS[mana_type])

    if regex.search(r"add (one|three) mana of any( one)? color", text, regex.IGNORECASE):
        result |= {"White", "Blue", "Black", "Red", "Green"}

    if regex.search(r"add one mana of that color", text, regex.IGNORECASE):
        result |= {"White", "Blue", "Black", "Red", "Green"}

    return result


# ---------------------------------------------------------------------------
# Parsing des fichiers "Moxfield"
# ---------------------------------------------------------------------------

MOXFIELD_LINE_RE = re.compile(
    r"""
    ^\s*
    (?P<count>\d+)          # nombre d'exemplaires
    \s+
    (?P<name>[^(]+?)        # nom de carte = tout avant le premier '('
    (?:\s+\((?P<set>[^)]+)\)   # code de set entre parenthèses
        (?:\s+(?P<cn>[^ ]+))?  # collector number éventuel
        .*?
    )?
    \s*$
    """,
    re.VERBOSE,
)


@dataclass
class CardEntry:
    count: int
    name: str
    set_code: Optional[str] = None
    collector_number: Optional[str] = None

    @property
    def cache_key(self) -> str:
        """Clé de cache stable dérivée de la ligne Moxfield."""
        set_part = (self.set_code or "no-set").upper()
        cn_part = self.collector_number or "no-num"
        # nom simplifié (sans espaces, caractères spéciaux)
        name_norm = re.sub(r"[^A-Za-z0-9]+", "_", self.name.strip())
        return f"{set_part}_{cn_part}_{name_norm}"


def parse_moxfield_file(path: str) -> List[CardEntry]:
    entries: List[CardEntry] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line.strip():
                continue
            if line.strip().startswith("#"):
                continue
            m = MOXFIELD_LINE_RE.match(line)
            if not m:
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[0].isdigit():
                    count = int(parts[0])
                    name = parts[1].strip()
                    entries.append(CardEntry(count=count, name=name))
                    continue
                else:
                    raise ValueError(f"Ligne invalide dans {path!r} : {line!r}")
            count = int(m.group("count"))
            name = m.group("name").strip()
            set_code = m.group("set")
            cn = m.group("cn")
            if set_code:
                set_code = set_code.strip().upper()
            if cn:
                cn = cn.strip()
            entries.append(CardEntry(count=count, name=name, set_code=set_code, collector_number=cn))
    return entries


# ---------------------------------------------------------------------------
# Génération du set MSE
# ---------------------------------------------------------------------------

def build_set_file(
    title: str,
    copyright_text: str,
    set_code: str,
    auto_card_numbers: bool,
    border_color: Optional[str],
) -> MSEDataFile:
    set_file = MSEDataFile()
    set_file["mse version"] = "0.3.8"
    set_file["game"] = "magic"
    set_file["stylesheet"] = "m15"

    set_info = {
        "title": title,
        "copyright": copyright_text,
        "description": "Cards automatically imported from Scryfall using listofcards-to-mse.",
        "set code": set_code,
        "set language": "FR",  # tu veux tout en français autant que possible
        "mark errors": "no",
        "automatic reminder text": "",
        "automatic card numbers": "yes" if auto_card_numbers else "no",
        "mana cost sorting": "unsorted",
    }
    if border_color is not None:
        set_info["border color"] = border_color
    set_file["set info"] = set_info

    set_file["styling"] = {
        "magic-m15": {
            "text box mana symbols": "magic-mana-small.mse-symbol-font",
            "center text": "short text only",
            "overlay": "",
        }
    }
    return set_file


def finalize_set_file(set_file: MSEDataFile) -> None:
    for stylesheet in set_file.stylesheets:
        if stylesheet == "m15":
            continue
        styling = {
            "text box mana symbols": "magic-mana-small.mse-symbol-font",
            "overlay": "",
        }
        if stylesheet in ("m15-split", "m15-split-fuse"):
            styling["center text 1"] = styling["center text 2"] = "always"
        elif stylesheet == "m15-textless-land":
            del styling["text box mana symbols"]
        else:
            styling["center text"] = "short text only"
        set_file["styling"][f"magic-{stylesheet}"] = styling

    set_file["version control"] = {"type": "none"}
    set_file["apprentice code"] = ""


def write_mse_set(set_file: MSEDataFile, output_path: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "x", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("set", str(set_file))
        for i, image_path in enumerate(set_file.images):
            zf.write(image_path, arcname=f"image{i + 1}")
    with open(output_path, "wb") as out:
        out.write(buf.getvalue())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_border_color(border_color: Optional[str]) -> Optional[str]:
    if border_color is None:
        return None
    if border_color == "black":
        return None
    if border_color in ("w", "white"):
        return "rgb(255,255,255)"
    if border_color in ("s", "silver"):
        return "rgb(128,128,128)"
    if border_color in ("g", "gold"):
        return "rgb(200,180,0)"
    if border_color in ("b", "bronze"):
        return "rgb(222,127,50)"
    raise ValueError(f"Unrecognized border color: {border_color}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convertit un fichier texte Moxfield en set .mse-set pour Magic Set Editor (M15)."
    )
    parser.add_argument(
        "input",
        help="Fichier texte d'entrée (format Moxfield : '1 Nom de carte (SET) 123 ...').",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Fichier .mse-set de sortie (par défaut : même nom que l'entrée avec extension .mse-set).",
    )
    parser.add_argument(
        "--images",
        help="Dossier où télécharger les illustrations (par défaut : 'mse-images').",
        default="mse-images",
    )
    parser.add_argument(
        "--set-code",
        help="Code de set à utiliser dans MSE (par défaut : PROXY).",
        default="PROXY",
    )
    parser.add_argument(
        "--title",
        help="Titre du set MSE (par défaut : 'MTG Scryfall import').",
        default="MTG Scryfall import",
    )
    parser.add_argument(
        "--copyright",
        help="Copyright affiché (par défaut : 'NOT FOR SALE').",
        default="NOT FOR SALE",
    )
    parser.add_argument(
        "--auto-card-numbers",
        help="Activer la numérotation automatique des cartes.",
        action="store_true",
    )
    parser.add_argument(
        "--border",
        help="Couleur de bordure : black, white, silver, gold, bronze.",
        default=None,
    )
    parser.add_argument(
        "--allow-uncards",
        help="Autoriser les Un-cards (silver border).",
        action="store_true",
    )
    parser.add_argument(
        "--new-wedge-order",
        help="Normaliser l'ordre des symboles de wedge (mana cost).",
        action="store_true",
    )
    parser.add_argument(
        "--verbose",
        help="Mode verbeux.",
        action="store_true",
    )

    args = parser.parse_args(argv)

    input_path = args.input
    if not os.path.isfile(input_path):
        parser.error(f"Fichier d'entrée introuvable : {input_path}")

    output_path = args.output
    if not output_path:
        base, _ = os.path.splitext(input_path)
        output_path = base + ".mse-set"

    try:
        border_color = parse_border_color(args.border)
    except ValueError as e:
        parser.error(str(e))

    entries = parse_moxfield_file(input_path)
    if not entries:
        parser.error("Aucune carte trouvée dans le fichier d'entrée.")

    if args.verbose:
        print(f"[....] {len(entries)} lignes de cartes lues", file=sys.stderr)

    set_file = build_set_file(
        title=args.title,
        copyright_text=args.copyright,
        set_code=args.set_code,
        auto_card_numbers=args.auto_card_numbers,
        border_color=border_color,
    )

    failed = 0
    images_to_add: List[str] = set_file.images

    for idx, entry in enumerate(entries, 1):
        if args.verbose:
            progress = min(4, 5 * idx // len(entries))
            print(
                f"[{'=' * progress}{'.' * (4 - progress)}] "
                f"Téléchargement / conversion : {idx} / {len(entries)}",
                end="\r",
                file=sys.stderr,
                flush=True,
            )
        for _ in range(entry.count):
            try:
                card = fetch_printing(
                    entry.set_code,
                    entry.collector_number,
                    entry.name,
                    preferred_lang="fr",
                    cache_key=entry.cache_key,
                )
                build_mse_card(
                    card,
                    set_file,
                    images_dir=args.images,
                    images_to_add=images_to_add,
                    allow_uncards=args.allow_uncards,
                    new_wedge_order=args.new_wedge_order,
                )
            except UncardError as e:
                failed += 1
                print(f"[ !! ] {entry.name}: {e}", file=sys.stderr)
            except requests.HTTPError as e:
                failed += 1
                print(f"[ !! ] {entry.name}: Scryfall HTTP error {e}", file=sys.stderr)
            except Exception as e:
                failed += 1
                if args.verbose:
                    print(f"[ !! ] Erreur pour {entry.name}: {e}", file=sys.stderr)
                else:
                    print(
                        f"[ !! ] Erreur pour {entry.name}. "
                        f"Relancez avec --verbose pour plus de détails.",
                        file=sys.stderr,
                    )

    finalize_set_file(set_file)
    write_mse_set(set_file, output_path)

    if args.verbose:
        print("\n[ ok ] Set MSE généré :", output_path, file=sys.stderr)
        if failed:
            print(f"[ ** ] {failed} cartes ont échoué.", file=sys.stderr)
    else:
        if failed:
            print(
                f"[ ** ] {failed} cartes ont échoué. "
                f"Relancez avec --verbose pour les détails.",
                file=sys.stderr,
            )
        print(output_path)


if __name__ == "__main__":
    main()
