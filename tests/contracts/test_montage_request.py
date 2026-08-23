import hashlib
from pathlib import Path

import pytest

from lib.montage_request import MontageRequestError, prepare_montage_request
from schemas.artifacts import validate_artifact


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_request_stages_hash_verified_inputs_without_mutating_sources(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    brief = source / "brief.md"
    music = source / "music.wav"
    video = source / "clip.mp4"
    brief.write_text("A fast product montage", encoding="utf-8")
    music.write_bytes(b"RIFF-fake-audio")
    video.write_bytes(b"fake-video")
    before = {path: _hash(path) for path in (brief, music, video)}

    request = prepare_montage_request({"input_dir": str(source)}, projects_root=tmp_path / "projects")

    validate_artifact("montage_request", request)
    assert request["settings"]["three_d_enabled"] is True
    assert request["settings"]["beat_sync_policy"] == "adaptive"
    assert all(_hash(path) == digest for path, digest in before.items())
    project_dir = Path(request["output"]["project_dir"])
    assert project_dir.is_dir()
    assert request["output"]["request_relative_path"] == "montage_request.json"
    for record in (request["brief"], request["music"], *request["media"]):
        staged = project_dir / record["staged_relative_path"]
        assert staged.is_file()
        assert staged.resolve() == Path(record["staged_path"]).resolve()
    assert request["music"]["sha256"] == before[music]


def test_explicit_slug_collision_fails_instead_of_overwriting(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "brief.md").write_text("brief")
    (source / "music.wav").write_bytes(b"music")
    (source / "clip.mp4").write_bytes(b"video")
    projects = tmp_path / "projects"
    prepare_montage_request({"input_dir": str(source), "slug": "my-cut"}, projects_root=projects)

    with pytest.raises(MontageRequestError) as exc:
        prepare_montage_request({"input_dir": str(source), "slug": "my-cut"}, projects_root=projects)
    assert exc.value.code == "PROJECT_EXISTS"


def test_multiple_music_files_are_ambiguous(tmp_path: Path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "brief.md").write_text("brief")
    (source / "a.wav").write_bytes(b"a")
    (source / "b.mp3").write_bytes(b"b")
    (source / "clip.mp4").write_bytes(b"video")
    with pytest.raises(MontageRequestError) as exc:
        prepare_montage_request({"input_dir": str(source)}, projects_root=tmp_path / "projects")
    assert exc.value.code == "MUSIC_AMBIGUOUS"
