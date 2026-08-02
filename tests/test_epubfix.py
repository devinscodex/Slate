"""epubfix.py: detects and corrects a real, confirmed epub authoring
bug -- an HTML content file's meta charset tag disagreeing with its
own XML encoding declaration. Confirmed live against a real epub
(Brandon Sanderson's "The Way of Kings") before writing this module;
the synthetic fixtures here reproduce the exact same conflict shape.
"""
import zipfile

import fitz

import epubfix


def _build_epub(path, html_content: bytes, filename="OEBPS/ch01.html"):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title>'
            '<dc:language>en</dc:language>'
            '<dc:identifier id="BookId">urn:uuid:test</dc:identifier></metadata>'
            f'<manifest><item id="ch1" href="{filename.split("/")[-1]}" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="ch1"/></spine></package>',
        )
        z.writestr(filename, html_content)


def test_no_conflict_returns_the_same_path_unchanged(tmp_path):
    """The common case: XML declaration and meta charset agree (or
    there's no meta charset at all) -- must return the ORIGINAL path,
    not write a needless temp copy."""
    path = str(tmp_path / "clean.epub")
    html = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b'<meta charset="utf-8"/></head>'
        b'<body><p>Plain ASCII text, no conflict here.</p></body></html>'
    )
    _build_epub(path, html)
    result = epubfix.fix_epub_encoding_conflicts(path)
    assert result == path


def test_conflicting_html5_meta_charset_is_corrected(tmp_path):
    """Reproduces the exact real-world shape: XML says UTF-8, an
    HTML5-style <meta charset="..."> says something else, actual bytes
    are real UTF-8 (a curly quote, U+201C, encoded as UTF-8)."""
    path = str(tmp_path / "conflict_html5.epub")
    smart_quote_utf8 = "“Hello”".encode("utf-8")
    html = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b'<meta charset="iso-8859-1"/></head>'
        b"<body><p>" + smart_quote_utf8 + b" world.</p></body></html>"
    )
    _build_epub(path, html)

    result = epubfix.fix_epub_encoding_conflicts(path)
    assert result != path  # a corrected temp copy was written

    doc = fitz.open(result)
    text = doc[0].get_text()
    assert "“Hello”" in text  # real smart quotes, not mojibake
    doc.close()


def test_conflicting_http_equiv_meta_charset_is_corrected(tmp_path):
    """The real Sanderson epub's exact form: an HTML4-style
    <meta http-equiv="Content-Type" content="text/html; charset=...">
    rather than the HTML5 <meta charset="...">."""
    path = str(tmp_path / "conflict_http_equiv.epub")
    ellipsis_utf8 = "one…two".encode("utf-8")
    html = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b'<meta content="text/html; charset=iso-8859-1" http-equiv="content-type"/></head>'
        b"<body><p>" + ellipsis_utf8 + b"</p></body></html>"
    )
    _build_epub(path, html)

    result = epubfix.fix_epub_encoding_conflicts(path)
    assert result != path

    doc = fitz.open(result)
    text = doc[0].get_text()
    assert "one…two" in text  # real ellipsis, not mojibake
    doc.close()


def test_original_file_is_never_modified(tmp_path):
    path = str(tmp_path / "conflict.epub")
    html = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b'<meta charset="iso-8859-1"/></head>'
        b"<body><p>test</p></body></html>"
    )
    _build_epub(path, html)
    original_bytes = open(path, "rb").read()

    epubfix.fix_epub_encoding_conflicts(path)

    assert open(path, "rb").read() == original_bytes  # untouched


def test_agreeing_meta_charset_is_left_alone_even_if_present(tmp_path):
    """A meta tag that matches the XML declaration must not be touched
    -- only a genuine disagreement is a real signal to act on."""
    path = str(tmp_path / "agreeing.epub")
    html = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        b'<meta charset="UTF-8"/></head>'
        b"<body><p>fine as-is</p></body></html>"
    )
    _build_epub(path, html)
    result = epubfix.fix_epub_encoding_conflicts(path)
    assert result == path
