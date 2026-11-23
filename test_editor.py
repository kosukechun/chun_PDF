from dataclasses import replace
import pytest
import engine as e


@pytest.fixture
def leaves(tmp_path):
    path = tmp_path / "資料 日本語.pdf"
    with e.pdf.open() as doc:
        for word in ["first", "second", "third"]:
            p = doc.new_page(width=280, height=180)
            p.insert_text((35, 45), word, fontsize=16)
        doc.save(path)
    return [e.Leaf(str(path), n) for n in range(3)]


def test_sequence(leaves, tmp_path):
    target = tmp_path / "編集.pdf"
    e.safe_save([leaves[2], leaves[0], leaves[0], e.Leaf()], target)
    with e.pdf.open(target) as d:
        assert [p.get_text().strip() for p in d] == ["third", "first", "first", ""]
    for group in ([leaves[0]], [leaves[1], leaves[2]]):
        e.safe_save(group, target)
        with e.pdf.open(target) as d:
            assert len(d) == len(group)


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_crop(leaves, angle, tmp_path):
    leaf = replace(leaves[0], turn=angle, crop=(10, 12, 245, 160))
    with e.Builder() as b:
        p = b.add(leaf)
        selected = e.pdf.Rect(20, 25, 90, 105)
        box = e.crop_coords(p, selected)
        expected = p.get_pixmap(clip=selected).samples
    with e.Builder() as b:
        cropped = b.add(replace(leaf, crop=box))
        assert (
            abs(cropped.rect.width - 70) < 0.01 and abs(cropped.rect.height - 80) < 0.01
        )
        assert cropped.get_pixmap().samples == expected


def test_password_and_damage(tmp_path):
    path = tmp_path / "鍵.pdf"
    with e.pdf.open() as doc:
        doc.new_page()
        doc.save(
            path, encryption=e.pdf.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="owner"
        )
    with pytest.raises(PermissionError):
        e.open_pdf(path)
    with e.open_pdf(path, "pw") as doc:
        assert len(doc) == 1
    broken = tmp_path / "bad.pdf"
    broken.write_bytes(b"bad")
    with pytest.raises(Exception):
        e.open_pdf(broken)


def test_range():
    assert e.pages("1-3, 5", 5) == [0, 1, 2, 4]
    for spec in ["0", "2-1", "1,1", "6", "1-2-3", "1,", "x"]:
        with pytest.raises(ValueError):
            e.pages(spec, 5)


def test_region_and_text(leaves):
    assert e.recognize(leaves[0], (0, 0, 150, 100), "jpn+eng") == "first"
    import io
    from PIL import Image

    blob, _ = e.render(leaves[0], 2, (10, 20, 40, 60))
    assert Image.open(io.BytesIO(blob)).size == (60, 80)


def test_compress(leaves, tmp_path):
    for comp in [(0, 0), (150, 75), (96, 48)]:
        p = tmp_path / "圧縮.pdf"
        e.safe_save(leaves, p, comp)
        with e.pdf.open(p) as doc:
            assert doc[1].get_text().strip() == "second"


def test_progress_cleanup(leaves, tmp_path):
    dest = tmp_path / "existing.pdf"
    dest.write_bytes(b"previous")

    def cancel(n, total):
        assert n == total == 3
        raise InterruptedError()

    with pytest.raises(InterruptedError):
        e.safe_save(leaves, dest, progress=cancel)
    assert dest.read_bytes() == b"previous"
    assert not list(tmp_path.glob("*.part"))
    with pytest.raises(ValueError):
        e.safe_save(leaves, leaves[0].path)


def test_autostart(monkeypatch):
    import winreg
    from uuid import uuid4
    import windows as win

    key = r"Software\chunPDFTest-" + uuid4().hex
    monkeypatch.setattr(win, "RUN", key)
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key):
            pass
    except PermissionError:
        pytest.skip("HKCU access denied by this test environment")
    try:
        win.set_autostart(True)
        assert win.autostart_enabled()
        win.set_autostart(False)
        assert not win.autostart_enabled()
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def test_bulk(tmp_path):
    target = tmp_path / "大量.pdf"
    e.safe_save([e.Leaf()] * 1500, target)
    with e.open_pdf(target) as doc:
        assert len(doc) == 1500


def test_multi_source_and_isolated_annotations(leaves, tmp_path):
    target = tmp_path / "二つ目.pdf"
    e.safe_save([leaves[2]], target)
    mark = ("文字", (12, 72, 160, 125), "追加の文字", 16, (0, 0.2, 0.4))
    marked = replace(leaves[0], marks=(mark,))
    merged = tmp_path / "結合.pdf"
    e.safe_save([leaves[0], e.Leaf(str(target)), marked], merged)
    with e.open_pdf(merged) as doc:
        assert doc[0].get_text().strip() == "first"
        assert doc[1].get_text().strip() == "third"
        assert "追加" in "".join(doc[2].get_text().split())


def test_raster(leaves, tmp_path):
    dest = tmp_path / "画像.pdf"
    e.safe_save(leaves[:1], dest, (120, 68, "raster"))
    with e.open_pdf(dest) as doc:
        assert doc[0].get_images() and not doc[0].get_text().strip()


def test_scaled_selection_on_nonzero_crop(leaves):
    leaf = replace(leaves[0], turn=90, crop=(10, 10, 220, 160))
    with e.Builder() as builder:
        page = builder.add(leaf)
        selected = e.pdf.Rect(40, 30, 90, 80)
        pdf_box = e.crop_coords(page, selected)
    blob, _ = e.render(leaf, 3, selected)
    cropped, _ = e.render(replace(leaf, crop=pdf_box), 3)
    import io
    from PIL import Image

    assert (
        Image.open(io.BytesIO(blob)).tobytes()
        == Image.open(io.BytesIO(cropped)).tobytes()
    )
