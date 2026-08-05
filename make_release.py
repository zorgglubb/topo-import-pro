#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_release.py — Script de création du ZIP de release pour TopoImport Pro
Auteurs : Mehdi Belarbi & Claude (Anthropic)

Usage :
    python3 make_release.py              → crée le ZIP avec la version de metadata.txt
    python3 make_release.py --check      → vérifie seulement la syntaxe
    python3 make_release.py --version    → affiche la version courante
"""
import os
import sys
import ast
import zipfile
import argparse
from pathlib import Path

ROOT = Path(__file__).parent
PLUGIN_DIR = ROOT / 'topo_import'

EXCLUDE_PATTERNS = {
    '__pycache__', '.pyc', '.pyo', '.DS_Store',
    'Thumbs.db', '.git', '.idea', '.vscode',
}


def get_version():
    meta = PLUGIN_DIR / 'metadata.txt'
    for line in meta.read_text(encoding='utf-8').splitlines():
        if line.startswith('version='):
            return line.split('=', 1)[1].strip()
    raise ValueError("Version non trouvée dans metadata.txt")


def check_syntax():
    errors = []
    py_files = list(PLUGIN_DIR.rglob('*.py'))
    for f in py_files:
        try:
            ast.parse(f.read_text(encoding='utf-8', errors='replace'))
            print(f"  ✅ {f.relative_to(ROOT)}")
        except SyntaxError as e:
            errors.append(f"  ❌ {f.relative_to(ROOT)} — ligne {e.lineno}: {e.msg}")
            print(errors[-1])
    return errors


def should_exclude(path: Path) -> bool:
    for part in path.parts:
        if any(exc in part for exc in EXCLUDE_PATTERNS):
            return True
    return False


def make_zip(version: str) -> Path:
    zip_name = ROOT / f"topo_import_pro_v{version}.zip"
    files_added = 0

    with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in PLUGIN_DIR.rglob('*'):
            if f.is_file() and not should_exclude(f):
                arcname = f.relative_to(ROOT)
                zf.write(f, arcname)
                files_added += 1

    size_kb = zip_name.stat().st_size // 1024
    print(f"\n✅ ZIP créé : {zip_name.name} ({size_kb} Ko, {files_added} fichiers)")
    return zip_name


def main():
    parser = argparse.ArgumentParser(description='Crée le ZIP de release TopoImport Pro')
    parser.add_argument('--check',   action='store_true', help='Vérifier la syntaxe seulement')
    parser.add_argument('--version', action='store_true', help='Afficher la version')
    args = parser.parse_args()

    version = get_version()

    if args.version:
        print(f"TopoImport Pro v{version}")
        return

    print(f"=== TopoImport Pro v{version} — Build ===\n")
    print("Vérification de la syntaxe Python...")
    errors = check_syntax()

    if errors:
        print(f"\n❌ {len(errors)} erreur(s) de syntaxe — ZIP non créé.")
        sys.exit(1)

    if args.check:
        print("\n✅ Syntaxe OK — aucun ZIP créé (mode --check).")
        return

    print(f"\nCréation du ZIP...")
    zip_path = make_zip(version)

    print(f"\nPour installer dans QGIS :")
    print(f"  Extensions → Gérer → Installer depuis un ZIP → {zip_path.name}")
    print(f"\nPour publier sur GitHub :")
    print(f"  git tag v{version}")
    print(f"  git push origin v{version}")
    print(f"  → La CI GitHub Actions créera la Release automatiquement")


if __name__ == '__main__':
    main()
