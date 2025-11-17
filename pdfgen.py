#!/usr/bin/env python3
# -*- coding: utf-8 -*-


from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from PIL import Image


CARD_W = 63 * mm
CARD_H = 88 * mm
COLS = 3
ROWS = 3


def generate_pdf(images, out_path):
    c = canvas.Canvas(out_path, pagesize=A4)
    page_w, page_h = A4

    x_spacing = CARD_W
    y_spacing = CARD_H

    col = 0
    row = 0

    for img_path in images:
        if col == COLS:
            col = 0
            row += 1
        if row == ROWS:
            c.showPage()
            col = 0
            row = 0

        x = col * x_spacing
        y = page_h - (row + 1) * y_spacing

        c.drawImage(img_path, x, y, width=CARD_W, height=CARD_H)

        col += 1

    c.save()
