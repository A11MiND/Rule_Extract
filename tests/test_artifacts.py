import zipfile

from backend.app.services.artifacts import extract_zip


def test_extract_zip_picks_full_markdown(tmp_path):
    storage = tmp_path / "storage"
    zip_path = tmp_path / "result.zip"

    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("doc/full.md", "# Full\nText")
        archive.writestr("doc/middle.json", "{\"pages\": []}")

    manifest = extract_zip(7, zip_path, storage_root=storage)

    assert manifest["markdown_path"].endswith("full.md")
    assert len(manifest["json_paths"]) == 1
    assert any(path.endswith("middle.json") for path in manifest["files"])
