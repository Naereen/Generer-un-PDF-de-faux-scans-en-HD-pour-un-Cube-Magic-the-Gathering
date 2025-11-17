# Script local en Python, pour générer un PDF prêt à être imprimé, de faux scans en HD pour un Cube Magic the Gathering via MTGRender.tk, Scryfall.com et Moxfield.com

## 📌 **Résumé**

**MTGFR-Render** est un outil complet permettant de générer automatiquement :

1. **des images HD** de cartes Magic en **version française**,
2. **avec exactement l'illustration utilisée** dans votre deck Moxfield,
3. en utilisant **Scryfall FR** + **MTGRender**,
4. puis un **PDF imprimable A4** au format **3×3 sans marges**, prêt à être découpé comme un *proxy cube* propre.

L'objectif est de remplacer MTGPrint lorsque l'on veut :

* les **bons artworks**,
* la **version française** (textes Oracle FR),
* une **qualité parfaite**,
* les **double-faced cards recto|verso côte à côte**,
* un **flux totalement automatisé**,
* et **un cache local** robuste pour reconstruire votre cube sans re-télécharger Scryfall.

---

# 🧩 **Pourquoi ce projet existe ?**

Le site MTGPrint.net est génial, mais il a 3 limitations majeures :

1. Il **n'autorise pas de sélectionner l'illustration exacte** choisie dans Moxfield.
2. Il **ne propose pas les scans FR** lorsque la qualité Scryfall FR est faible.
3. Il ne permet pas de **rendu HD alternatif** (proxies propres) avec des outils comme MTGRender.

Ce projet résout totalement ces problèmes en générant des **faux scans HD parfaits**, basés sur :

* **MTGRender** pour le rendu vectoriel propre
* **Scryfall FR** pour les textes
* **Moxfield** pour l'identification exacte des illustrations
* un **PDF A4 3×3** identique au workflow MTGPrint

---

# 🚀 **Fonctionnalités principales**

### ✔️ **1. Récupération automatique de decks Moxfield**

* Extraction du deck complet (mainboard uniquement)
* Récupération des IDs Scryfall exacts utilisés sur Moxfield
* Gestion des versions particulières, showcases, alt arts, etc.

### ✔️ **2. Récupération Scryfall FR**

* Appel automatique à l'API : `?lang=fr`
* Utilisation des champs :

  * `printed_name`
  * `printed_text`
  * `printed_type_line`
* Fallback vers Oracle EN uniquement si FR indisponible

### ✔️ **3. Gestion complète des double-faced cards**

* Récupération des deux faces
* Téléchargement de deux illustrations
* Rendu MTGRender des deux faces
* Placement côte-à-côte dans la séquence d'images destinée au PDF
  (Exactement comme MTGPrint le fait)

### ✔️ **4. Rendu HD via MTGRender**

Le rendu produit :

* nom
* coût de mana
* type
* texte Oracle FR
* illustration HD officielle
* cadre HD
* export PNG haute définition

### ✔️ **5. PDF imprimable A4**

* Format **A4**
* **3 colonnes × 3 lignes**
* **0 marges** (bord à bord)
* Dimensions exactes : **63 mm × 88 mm**
* Intègre les double-faced cards comme deux cartes séparées
* Prêt à découper, compatible imprimeries

### ✔️ **6. Système de cache local intelligent**

Dans `cache/` :

```
cache/
  cards/     -> cache JSON Scryfall
  arts/      -> illustrations HD
  renders/   -> images mtgrender prêtes
```

Permet :

* reconstruction ultra-rapide
* aucun appel Scryfall répété
* reprise en cas d'interruption
* cohérence entre runs

### ✔️ **7. CLI avancée**

Commandes :

| Option             | Description                                        |
| ------------------ | -------------------------------------------------- |
| `--no-cache`       | ignore le cache (mais continue d'en écrire)        |
| `--refresh`        | supprime uniquement les caches JSON + arts         |
| `--clean`          | supprime entièrement le cache                      |
| `--force-rerender` | force le recalcul de toutes les images             |
| `--no-pdf`         | génère uniquement les PNG                          |
| `--only-pdf`       | ne génère le PDF qu'à partir des images existantes |

---

# 📦 Installation

### 1. Cloner le projet / récupérer les fichiers

```
git clone <ton_repos> mtgfr-render
cd mtgfr-render
```

### 2. Créer un environnement Python

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Installer les dépendances

```bash
pip install -r python_pip_requirements.txt
```

### 4. Installer MTGRender

(Depuis pip — pas besoin de git clone)

```bash
pip install mtgrender
```

C'est tout.

---

# 🔧 Utilisation

## **Générer images + PDF (mode par défaut)**

```bash
python3 main.py render https://www.moxfield.com/decks/XXXXXX
```

Résultats :

```
output/
  <deckname>.pdf
  card1_0.png
  card1_1.png    # verso si DFC
  card2.png
  ...
```

---

## **Uniquement les images**

```bash
python3 main.py render <url> --no-pdf
```

## **Uniquement le PDF (si images déjà présentes)**

```bash
python3 main.py render <url> --only-pdf
```

---

## **Forcer un rerender complet (mtgrender)**

```bash
python3 main.py render <url> --force-rerender
```

---

## **Purges de cache**

Effacer uniquement JSON et illustrations :

```bash
python3 main.py render <url> --refresh
```

Effacer tout le cache :

```bash
python3 main.py render <url> --clean
```

---

# 🔍 Détails techniques complets

### 📥 **1. API Moxfield**

Le script appelle :

```
GET https://api2.moxfield.com/v2/decks/all/<deck_id>
```

Ces données incluent l'ID Scryfall exact utilisé dans l'interface Moxfield.

---

### 🌐 **2. API Scryfall FR**

Pour chaque carte :

```
https://api.scryfall.com/cards/<scry_id>?lang=fr
```

Champs utilisés :

* printed_name
* printed_type_line
* printed_text
* mana_cost
* oracle_id
* image_uris / card_faces[n].image_uris

---

### 🎨 **3. Rendu via MTGRender**

Commande typique :

```
mtgrender render \
  --name "Nom FR" \
  --mana-cost "{1}{W}" \
  --type-line "Créature — Humain" \
  --oracle-text "Texte Oracle en FR" \
  --art path/to/art.png \
  --output output/name.png
```

Support complet des double-faced cards :

* deux appels MTGRender
* deux fichiers PNG générés

---

### 📄 **4. Génération PDF A4**

* réalisé avec `reportlab`
* carte dimensionnée en mm
* positionnement exact :

  * COLS = 3
  * ROWS = 3
* 9 cartes par page
* pages ajoutées automatiquement si nécessaire
* prend en entrée la liste de fichiers PNG déjà générés

---

### 🗄️ **5. Cache local**

Le cache réduit drastiquement le temps de reconstruction du cube.

Indicateurs :

| Élément           | Cache ? | Quand rechargé ?               |
| ----------------- | ------- | ------------------------------ |
| JSON Scryfall     | ✔️      | jamais tant que fichier existe |
| Illustrations     | ✔️      | idem                           |
| Renders MTGRender | ✔️      | sauf si `--force-rerender`     |

---

# 🎨 Reproductibilité & qualité

* Toutes les images sont en PNG HD (300–600 DPI suivant l'illustration Scryfall)
* Le PDF ne compresse pas les images
* Les dimensions physiques sont exactes (63×88 mm)
* Les DFC sont rendues identiquement à MTGPrint mais **en HD**

---

# 🛠️ Dépannage

## « mtgrender: command not found »

Installe MTGRender dans le même environnement Python :

```bash
pip install mtgrender
```

## Erreurs Scryfall

Le cache se remplit mal → :

```bash
python3 main.py render <url> --refresh
```

## PDF vide

Vérifier qu'il y a bien des images dans `output/`.

---

# 📜 Licence

Projet libre d'utilisation personnelle non-commerciale
(compatible avec la philosophie des proxies pour cubes privés).

---

# ❤️ Remerciements

* **Scryfall** pour sa base de données ouverte et exemplaire
* **MTGRender** (Senryoku) pour un outil formidable
* **Moxfield** pour une API fiable
* **ReportLab** pour du PDF pro
