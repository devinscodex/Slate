"""Fixes an epub authoring bug: some epub HTML/XHTML content files
declare one encoding via their own XML declaration
(<?xml version="1.0" encoding="UTF-8"?>) but a DIFFERENT, conflicting
one via an HTML meta charset tag in the same <head> -- MuPDF honors the
meta tag, misdecoding genuinely correct bytes when the two disagree.

Deliberately narrow: only acts when the two declarations genuinely
disagree (an unambiguous signal), not a general charset-sniffing/
guessing pass. Never touches the original file -- writes a corrected
temp copy and returns its path; the original is untouched.
"""
import re
import tempfile
import zipfile

_XML_ENCODING_RE = re.compile(rb'<\?xml[^>]*\bencoding=["\']([^"\']+)["\']', re.IGNORECASE)
_META_CHARSET_HTML5_RE = re.compile(rb'(<meta[^>]*\bcharset=["\'])([^"\']+)(["\'])', re.IGNORECASE)
_META_CHARSET_HTTP_EQUIV_RE = re.compile(
    rb'(<meta[^>]*content=["\'][^"\']*charset=)([^"\';\s]+)', re.IGNORECASE
)


def _replace_if_conflicting(pattern, data: bytes, xml_encoding: str):
    """Returns (possibly-modified data, whether it changed). Only
    rewrites when the meta tag's own encoding differs from the file's
    XML-declared one -- an agreeing meta tag is left alone."""
    m = pattern.search(data)
    if m is None:
        return data, False
    meta_encoding = m.group(2).decode("ascii", errors="ignore")
    if meta_encoding.lower() == xml_encoding.lower():
        return data, False
    fixed = data[: m.start(2)] + xml_encoding.encode("ascii") + data[m.end(2):]
    return fixed, True


def _fix_content(data: bytes) -> bytes:
    """Returns data unchanged unless it has BOTH an XML encoding
    declaration and a meta charset tag that genuinely disagree, in
    which case the meta tag is corrected to match the XML declaration
    (which is what actually governs XML/XHTML parsing, per spec)."""
    xml_match = _XML_ENCODING_RE.search(data)
    if xml_match is None:
        return data
    xml_encoding = xml_match.group(1).decode("ascii", errors="ignore")

    data, _ = _replace_if_conflicting(_META_CHARSET_HTML5_RE, data, xml_encoding)
    data, _ = _replace_if_conflicting(_META_CHARSET_HTTP_EQUIV_RE, data, xml_encoding)
    return data


def fix_epub_encoding_conflicts(path: str) -> str:
    """Returns `path` unchanged if no content file inside has a
    conflicting meta charset (the common case -- no new file is ever
    written then), or the path to a corrected TEMP copy (the original
    is never touched) if at least one file did conflict. Caller is
    responsible for opening whichever path this returns."""
    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        html_names = [n for n in names if n.lower().endswith((".html", ".xhtml", ".htm"))]

        any_changed = False
        fixed_content = {}
        for name in html_names:
            original = zin.read(name)
            fixed = _fix_content(original)
            if fixed != original:
                any_changed = True
                fixed_content[name] = fixed

        if not any_changed:
            return path

        tmp = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
        tmp.close()
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in names:
                data = fixed_content.get(name)
                if data is None:
                    data = zin.read(name)
                zout.writestr(name, data)
        return tmp.name
