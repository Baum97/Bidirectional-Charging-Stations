#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Bootstrap installer for pip.
"""
import os
import sys
import tempfile
import shutil
import argparse
import subprocess
import ensurepip


def main(args=None):
    parser = argparse.ArgumentParser(description="Install pip and setuptools")
    parser.add_argument("--user", action="store_true", help="Install for the current user")
    parser.add_argument("--upgrade", action="store_true", help="Upgrade existing pip")
    parser.add_argument("--force-reinstall", action="store_true", help="Reinstall all packages even if they are already installed")
    opts = parser.parse_args(args)

    # Try to use built-in ensurepip first
    try:
        ensurepip.bootstrap(upgrade=opts.upgrade, user=opts.user)
        print("Pip installation using ensurepip completed.")
        return
    except Exception as e:
        print("ensurepip failed:", e)

    # Fallback: use pip itself (bundled with ensurepip)
    python_exe = sys.executable
    try:
        subprocess.check_call([python_exe, "-m", "pip", "install", "--upgrade", "pip"])
        print("Pip upgraded via pip module.")
        return
    except Exception as e:
        print("Fallback pip installation failed:", e)

    # Final fallback: download pip via pip.pyz
    try:
        import urllib.request
        pip_url = "https://bootstrap.pypa.io/pip/pip.pyz"
        with urllib.request.urlopen(pip_url) as r:
            data = r.read()
        temp_dir = tempfile.mkdtemp()
        pip_file = os.path.join(temp_dir, "pip.pyz")
        with open(pip_file, "wb") as f:
            f.write(data)
        subprocess.check_call([python_exe, pip_file, "install", "--upgrade", "pip"])
        print("Pip installed via pip.pyz fallback.")
    except Exception as e:
        print("pip.pyz fallback failed:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
