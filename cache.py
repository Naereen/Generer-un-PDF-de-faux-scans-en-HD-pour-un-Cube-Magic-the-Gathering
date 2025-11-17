#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import os
import json
import shutil


class CacheManager:

    def __init__(self, no_cache=False, refresh=False, clean=False, base="cache"):
        self.base = base
        self.no_cache = no_cache

        if clean:
            shutil.rmtree(base, ignore_errors=True)

        if refresh:
            shutil.rmtree(os.path.join(base, "cards"), ignore_errors=True)
            shutil.rmtree(os.path.join(base, "arts"), ignore_errors=True)

        os.makedirs(base, exist_ok=True)
        os.makedirs(os.path.join(base, "cards"), exist_ok=True)
        os.makedirs(os.path.join(base, "arts"), exist_ok=True)
        os.makedirs(os.path.join(base, "renders"), exist_ok=True)

    # JSON
    def load_json(self, folder, filename):
        if self.no_cache:
            return None
        path = os.path.join(self.base, folder, filename)
        if not os.path.exists(path):
            return None
        with open(path, "r") as f:
            return json.load(f)

    def save_json(self, folder, filename, data):
        path = os.path.join(self.base, folder, filename)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    # binary
    def load_binary(self, folder, filename):
        if self.no_cache:
            return None
        path = os.path.join(self.base, folder, filename)
        return path if os.path.exists(path) else None

    def save_binary(self, folder, filename, content):
        path = os.path.join(self.base, folder, filename)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def save_file_copy(self, folder, filename, source):
        import shutil
        path = os.path.join(self.base, folder, filename)
        shutil.copy(source, path)
        return path


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
