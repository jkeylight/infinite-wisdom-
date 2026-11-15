from pathlib import Path

from converter.bulk import run_bulk, scan_inputs
from tests.make_fixtures import make_epub, make_pdf


def test_scan_recursive(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.epub").write_bytes(b"x")
    (tmp_path / "y.pdf").write_bytes(b"y")
    (tmp_path / "z.txt").write_bytes(b"z")
    found = scan_inputs([tmp_path])
    assert len(found) == 2


def test_bulk_and_skip_existing(tmp_path: Path):
    src_dir = tmp_path / "books"
    src_dir.mkdir()
    make_epub(src_dir / "a.epub")
    make_pdf(src_dir / "b.pdf")
    out = tmp_path / "converted"

    results = run_bulk([src_dir], out, workers=2, layout="mirror")
    assert sum(1 for r in results if r.status == "ok") == 2
    assert (out / "a" / "content.txt").exists()
    assert (out / "b" / "content.txt").exists()

    # Second run: skip existing
    results2 = run_bulk([src_dir], out, workers=2, layout="mirror", skip_existing=True)
    assert all(r.status == "skipped" for r in results2)

    # Force re-convert
    results3 = run_bulk([src_dir], out, workers=2, layout="mirror", skip_existing=False)
    assert sum(1 for r in results3 if r.status == "ok") == 2
