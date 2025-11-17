#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re

def slug(name: str):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name)
