"""Vision → text-only photo context handoff."""

from services import vision_handoff as vh


def test_split_photo_context_block():
    raw = (
        "E o pisică gri pe canapea.\n\n"
        "<<<photo_context>>>\n"
        "Gray cat on a beige sofa, daylight from the left.\n"
        "<<<end_photo_context>>>"
    )
    visible, ctx = vh.split_photo_context(raw)
    assert visible == "E o pisică gri pe canapea."
    assert "Gray cat" in ctx
    assert "<<<" not in visible


def test_split_unclosed_photo_context():
    raw = "Salut.\n<<<photo_context>>>\nDense notes without close"
    visible, ctx = vh.split_photo_context(raw)
    assert visible == "Salut."
    assert "Dense notes" in ctx


def test_finalize_falls_back_to_answer():
    visible, ctx = vh.finalize_reply("Doar un răspuns scurt, fără bloc.")
    assert visible.startswith("Doar")
    assert "răspuns scurt" in ctx


def test_stream_filter_hides_block():
    f = vh.PhotoContextStreamFilter()
    a = f.feed("Uite poza. ")
    b = f.feed("<<<photo_context>>>\ncat on sofa\n<<<end_photo_context>>>")
    c = f.feed(" gata")
    shown = a + b + c
    assert "Uite poza." in shown
    assert "photo_context" not in shown
    assert "cat on sofa" not in shown
    visible, ctx = f.finish()
    assert "cat on sofa" in ctx


def test_format_and_collect():
    rows = [
        {"role": "assistant", "content": "hi", "photo_context": "first photo"},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "more", "photo_context": "second photo"},
    ]
    ctxs = vh.collect_photo_contexts(rows)
    assert ctxs == ["first photo", "second photo"]
    block = vh.format_photo_context_block(ctxs, lang="ro")
    assert "Context foto" in block
    assert "second photo" in block
