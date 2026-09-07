"""Input image handling: formats, paths, and honest errors.

The pipeline is run by people pasting paths from a file manager, so this
covers the messy real-world cases as well as the clean ones.
"""

import numpy as np
import pytest

import cv2

from utils.imaging import (
    MAX_DETECTION_EDGE,
    SUPPORTED_EXTENSIONS,
    ImageError,
    decode_bytes,
    load_image,
    resolve_image_path,
    sniff_format,
)


@pytest.fixture()
def sample():
    """A small deterministic BGR image."""
    image = np.zeros((60, 40, 3), dtype=np.uint8)
    image[:, :] = (20, 120, 220)
    return image


def write(tmp_path, sample, name):
    path = tmp_path / name
    assert cv2.imwrite(str(path), sample)
    return path


# --- format detection -------------------------------------------------------


@pytest.mark.parametrize("name", ["a.jpg", "a.jpeg", "a.JPG", "a.JPEG"])
def test_every_jpeg_extension_spelling_loads(tmp_path, sample, name):
    """The headline case: .jpg and .jpeg, any capitalisation."""
    loaded = load_image(write(tmp_path, sample, name))
    assert loaded.image_format == "JPEG"
    assert loaded.width == 40 and loaded.height == 60


@pytest.mark.parametrize(
    "name,expected",
    [("a.png", "PNG"), ("a.bmp", "BMP"), ("a.tiff", "TIFF"), ("a.webp", "WEBP")],
)
def test_other_supported_formats_load(tmp_path, sample, name, expected):
    assert load_image(write(tmp_path, sample, name)).image_format == expected


def test_format_comes_from_content_not_extension(tmp_path, sample):
    """A PNG named .jpg must be recognised as a PNG, not trusted blindly."""
    png = write(tmp_path, sample, "real.png")
    liar = tmp_path / "liar.jpg"
    liar.write_bytes(png.read_bytes())

    loaded = load_image(liar)
    assert loaded.image_format == "PNG"
    assert loaded.is_uploadable  # SerpApi takes PNG, so no re-encode needed


def test_a_file_with_no_extension_still_loads(tmp_path, sample):
    source = write(tmp_path, sample, "x.jpg")
    bare = tmp_path / "photo"
    bare.write_bytes(source.read_bytes())
    assert load_image(bare).image_format == "JPEG"


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"\xff\xd8\xff\xe0" + b"\x00" * 8, "JPEG"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "PNG"),
        (b"RIFF\x00\x00\x00\x00WEBP", "WEBP"),
        (b"GIF89a" + b"\x00" * 8, "GIF"),
        (b"BM" + b"\x00" * 12, "BMP"),
        (b"II*\x00" + b"\x00" * 8, "TIFF"),
        (b"\x00\x00\x00\x18ftypheic", "HEIF"),
        (b"\x00\x00\x00\x18ftypavif", "AVIF"),
    ],
)
def test_magic_bytes_are_identified(data, expected):
    assert sniff_format(data) == expected


def test_unrecognised_bytes_return_none():
    assert sniff_format(b"this is just text, not an image") is None
    assert sniff_format(b"") is None
    assert sniff_format(b"\xff\xd8") is None  # too short to judge


# --- errors -----------------------------------------------------------------


def test_missing_file_names_the_path(tmp_path):
    with pytest.raises(ImageError, match="Image not found"):
        load_image(tmp_path / "nope.jpg")


def test_directory_is_rejected_clearly(tmp_path):
    with pytest.raises(ImageError, match="directory, not an image"):
        load_image(tmp_path)


def test_empty_file_is_rejected(tmp_path):
    (tmp_path / "empty.jpg").write_bytes(b"")
    with pytest.raises(ImageError, match="empty"):
        load_image(tmp_path / "empty.jpg")


def test_non_image_content_lists_supported_formats(tmp_path):
    (tmp_path / "notes.jpg").write_bytes(b"just some text pretending to be a photo")
    with pytest.raises(ImageError) as excinfo:
        load_image(tmp_path / "notes.jpg")
    for extension in (".jpg", ".jpeg", ".png"):
        assert extension in str(excinfo.value)


def test_heic_error_explains_how_to_convert(tmp_path):
    """iPhone photos are the most likely unsupported input, so say what to do."""
    (tmp_path / "IMG_0001.heic").write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 32)
    with pytest.raises(ImageError) as excinfo:
        load_image(tmp_path / "IMG_0001.heic")
    message = str(excinfo.value)
    assert "HEIF" in message
    assert "sips -s format jpeg" in message


def test_truncated_image_is_reported_as_undecodable(tmp_path, sample):
    source = write(tmp_path, sample, "x.png")
    broken = tmp_path / "broken.png"
    broken.write_bytes(source.read_bytes()[:20])
    with pytest.raises(ImageError, match="could not be|not a recognised"):
        load_image(broken)


# --- path handling ----------------------------------------------------------


def test_tilde_is_expanded():
    assert not str(resolve_image_path("~/x.jpg")).startswith("~")


def test_surrounding_quotes_and_whitespace_are_stripped():
    assert resolve_image_path('  "/tmp/a b.jpg"  ').as_posix() == "/tmp/a b.jpg"
    assert resolve_image_path("'/tmp/x.jpg'").as_posix() == "/tmp/x.jpg"


def test_an_apostrophe_inside_a_name_is_preserved():
    assert resolve_image_path("/tmp/bhanu's photo.jpg").name == "bhanu's photo.jpg"


def test_non_ascii_filenames_load(tmp_path, sample):
    path = write(tmp_path, sample, "照片 selfie.jpeg")
    assert load_image(path).image_format == "JPEG"


def test_filename_with_spaces_loads(tmp_path, sample):
    assert load_image(write(tmp_path, sample, "my holiday photo.jpg")).image_format == "JPEG"


# --- decoding and downscaling ----------------------------------------------


def test_decode_bytes_rejects_non_image_input():
    assert decode_bytes(b"") is None
    assert decode_bytes(b"not an image") is None


def test_small_images_are_not_downscaled(tmp_path, sample):
    loaded = load_image(write(tmp_path, sample, "small.jpg"))
    assert loaded.for_detection().shape == loaded.bgr.shape


def test_very_large_images_are_downscaled_for_detection(tmp_path):
    big = np.zeros((MAX_DETECTION_EDGE + 800, 300, 3), dtype=np.uint8)
    path = tmp_path / "big.png"
    cv2.imwrite(str(path), big)

    loaded = load_image(path)
    assert max(loaded.for_detection().shape[:2]) == MAX_DETECTION_EDGE
    # The original stays intact for hashing and upload.
    assert loaded.height == MAX_DETECTION_EDGE + 800


def test_supported_extensions_include_both_jpeg_spellings():
    assert ".jpg" in SUPPORTED_EXTENSIONS
    assert ".jpeg" in SUPPORTED_EXTENSIONS
