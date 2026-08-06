def test_clear_reader_cache_keeps_only_thumbnail(tmp_path):
    import fitz

    from pdf_viewer import page_renderer

    pdf = tmp_path / "m.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    doc.save(str(pdf))
    doc.close()

    # Vignette (page 1, zoom bibliothèque) + pages lues HD multi-zoom.
    page_renderer.render_page(str(pdf), 1, page_renderer.THUMBNAIL_ZOOM)  # vignette
    page_renderer.render_page(str(pdf), 1, 2.5)
    page_renderer.render_page(str(pdf), 2, 2.5)
    page_renderer.render_page(str(pdf), 3, 4.0)

    cache_dir = page_renderer.page_cache_dir(str(pdf))
    try:
        assert len(list(cache_dir.glob("page_*.png"))) == 4

        page_renderer.clear_reader_cache(str(pdf))

        remaining = sorted(p.name for p in cache_dir.glob("page_*.png"))
        assert remaining == ["page_001_z0.5.png"]
    finally:
        page_renderer.clear_page_cache(str(pdf))
