"""Zip a target's downloaded output folder."""
import os
import zipfile


def zip_dir(source_dir, zip_path):
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(source_dir):
            for file in files:
                full = os.path.join(root, file)
                arcname = os.path.relpath(full, os.path.dirname(source_dir))
                zf.write(full, arcname)
    return zip_path
