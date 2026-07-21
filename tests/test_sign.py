"""Slice 6 check: sign with a self-signed test cert; verify via pyHanko's
own independent validation call against the saved file."""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sign  # noqa: E402


def _make_fixture(path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "To be signed", fontsize=14)
    doc.save(path)
    doc.close()


def test_sign_and_independently_validate(tmp_path):
    key_path = str(tmp_path / "key.pem")
    cert_path = str(tmp_path / "cert.pem")
    src = str(tmp_path / "src.pdf")
    signed = str(tmp_path / "signed.pdf")

    sign.generate_self_signed_cert(key_path, cert_path)
    _make_fixture(src)

    signer = sign.load_signer(key_path, cert_path)
    sign.sign(src, signed, signer)

    assert sign.is_signed(signed)
    assert not sign.is_signed(src)  # sanity: the unsigned source isn't

    results = sign.validate(signed)
    assert len(results) == 1
    status = results[0]
    assert status.intact, "signature should cover the file and be intact"
    assert status.valid, "cryptographic signature check should pass"
    assert status.trusted, "self-signed cert used as its own trust root"


def test_signed_file_is_tamper_evident(tmp_path):
    """Flip one byte of the signed content and confirm validation
    correctly reports the signature as no longer intact -- proves the
    signature actually covers real content, not just a rubber stamp."""
    key_path = str(tmp_path / "key.pem")
    cert_path = str(tmp_path / "cert.pem")
    src = str(tmp_path / "src.pdf")
    signed = str(tmp_path / "signed.pdf")

    sign.generate_self_signed_cert(key_path, cert_path)
    _make_fixture(src)
    signer = sign.load_signer(key_path, cert_path)
    sign.sign(src, signed, signer)

    with open(signed, "rb") as f:
        data = bytearray(f.read())

    # Flip a byte inside the actual page content stream. PyMuPDF stores
    # inserted text as hex-encoded glyph codes, not literal ASCII (same
    # finding as test_redact.py) -- search for the hex form.
    needle = b"be signed".hex().encode()
    idx = data.find(needle)
    assert idx != -1, "fixture text not found -- test setup itself is wrong"
    data[idx] ^= 0xFF
    tampered = str(tmp_path / "tampered.pdf")
    with open(tampered, "wb") as f:
        f.write(data)

    results = sign.validate(tampered)
    assert len(results) == 1
    assert not results[0].intact, (
        "expected tampering to break signature integrity -- if this "
        "passed, the signature isn't actually covering real content"
    )
