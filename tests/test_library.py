"""
The local library.

A downloaded STL is a frozen mesh: you cannot make it 20 mm wider, cannot
change it for a different printer, cannot ask it anything. Every part here is a
SPEC, so it rebuilds exactly, at whatever size, in whatever material. That is
why this indexes spec.yaml rather than *.stl, and why sharing sends a spec.

Nothing here opens a socket.
"""

from pathlib import Path

import pytest

from bpcad import api, library

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def entries():
    return library.scan([ROOT / "parts"])


def test_the_library_finds_the_parts(entries):
    names = {e.name for e in entries}
    assert {"vent_louvre", "loop_keyring"} <= names


def test_an_entry_knows_its_template_without_building(entries):
    vent = next(e for e in entries if e.name == "vent_louvre")
    assert vent.template == "louvre_vent"
    assert vent.material == "petg"
    assert vent.built


def test_the_envelope_comes_from_the_stored_baseline(entries):
    """
    Read from regression.json rather than by loading every mesh - a library
    that measures its whole contents to draw a list is a library that takes a
    second to open.
    """
    vent = next(e for e in entries if e.name == "vent_louvre")
    assert vent.envelope_mm is not None
    assert vent.volume_cm3 > 20


def test_search_matches_the_name(entries):
    assert [e.name for e in library.search("keyring", entries)] == ["loop_keyring"]


def test_search_matches_what_the_template_makes(entries):
    """
    The point of the whole thing. "Container" appears nowhere in the birdhouse's
    spec - it comes from the enclosure template's own list of what people call
    it. Without that, a search only finds what you happened to name things.
    """
    hits = library.search("container", entries)
    assert hits, "a part built from the enclosure should answer to 'container'"
    assert all(e.template == "enclosure" for e in hits)


def test_search_matches_the_material(entries):
    assert len(library.search("petg", entries)) >= 2


def test_every_word_has_to_match(entries):
    assert library.search("vent keyring", entries) == []


def test_an_empty_search_returns_everything(entries):
    assert len(library.search("   ", entries)) == len(entries)


def test_search_is_case_insensitive(entries):
    assert library.search("VENT", entries) == library.search("vent", entries)


def test_a_draft_is_listed_and_marked(tmp_path):
    """
    A handoff that still needs editing is part of the library - hiding it is
    how a failed run gets forgotten about.
    """
    d = tmp_path / "halfdone"
    d.mkdir()
    (d / "spec.draft.yaml").write_text("name: halfdone\nlevel: 1\n")
    entry = library.read_entry(d)
    assert entry is not None
    assert entry.is_draft
    assert entry.summary() == "needs editing"


def test_a_directory_that_is_not_a_part_is_skipped(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "readme.txt").write_text("hello")
    assert library.read_entry(tmp_path / "notes") is None


# -- sharing ----------------------------------------------------------------


def test_a_shared_spec_is_small_and_readable(tmp_path, entries):
    vent = next(e for e in entries if e.name == "vent_louvre")
    out = api.export_spec(vent, tmp_path)
    assert out.is_file()
    assert out.stat().st_size < 8000, "a spec is text, not a mesh"
    assert "template: louvre_vent" in out.read_text()


def test_a_shared_spec_rebuilds_identically(tmp_path, entries):
    """
    The argument for specs over meshes, tested rather than asserted: a
    1 kB text file reproduces the part exactly.
    """
    from bpcad.verify.regression import signature_of

    vent = next(e for e in entries if e.name == "vent_louvre")
    shared = api.export_spec(vent, tmp_path / "outbox")
    brought_in = api.import_spec(shared, into=tmp_path / "library")
    rebuilt = api.build(spec_path=brought_in.spec_path, out_dir=tmp_path / "built")

    original = api.verify(ROOT / "reference" / "vent_louvre.stl")
    assert signature_of(rebuilt.report.mesh).digest() == signature_of(original.mesh).digest()


def test_sharing_a_draft_is_refused(tmp_path):
    d = tmp_path / "halfdone"
    d.mkdir()
    (d / "spec.draft.yaml").write_text("name: halfdone\n")
    entry = library.read_entry(d)
    with pytest.raises(api.ApiError) as exc:
        api.export_spec(entry, tmp_path / "out.yaml")
    assert "still needs editing" in str(exc.value)


def test_an_invalid_spec_is_refused_on_the_way_in(tmp_path):
    """
    Better a clear message here than a confusing one at build time.
    """
    bad = tmp_path / "bad.spec.yaml"
    bad.write_text("name: x\nlevel: 1\nmaterial: petg\nnozzle_mm: -5\nlayer_mm: 0.2\n")
    with pytest.raises(api.ApiError) as exc:
        api.import_spec(bad, into=tmp_path / "lib")
    assert "nozzle_mm" in str(exc.value)


def test_importing_twice_does_not_overwrite(tmp_path, entries):
    vent = next(e for e in entries if e.name == "vent_louvre")
    shared = api.export_spec(vent, tmp_path / "outbox")
    a = api.import_spec(shared, into=tmp_path / "lib")
    b = api.import_spec(shared, into=tmp_path / "lib")
    assert a.directory != b.directory


def test_a_spec_that_needs_a_file_takes_it_along(tmp_path):
    """
    The keyring's spec points at a traced logo. A shared spec that leaves it
    behind builds nothing at the other end.
    """
    keyring = next(e for e in library.scan([ROOT / "parts"]) if e.name == "loop_keyring")
    if "logo_json" not in keyring.params:
        pytest.skip("this keyring does not use a traced logo")
    out = api.export_spec(keyring, tmp_path / "outbox")
    assert (out.parent / keyring.params["logo_json"]).is_file()


def test_the_library_never_opens_a_socket(monkeypatch):
    """It reads directories. That is all it does."""
    import socket

    real = socket.socket

    class Blocked(real):
        def __init__(self, *a, **k):
            raise AssertionError("the library must not touch the network")

    monkeypatch.setattr(socket, "socket", Blocked)
    assert library.scan([ROOT / "parts"])
    assert library.search("container", roots=[ROOT / "parts"]) is not None
