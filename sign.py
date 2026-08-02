"""Digital signing -- pyHanko-backed, real PAdES (not PyMuPDF's own
basic/visual-only signature fields, per DESIGN.md). v1 ships PAdES B-B
(baseline, no timestamp/revocation -- fine for internal MEG sign-off).
B-LT/B-LTA (long-term validation) is a business question, not an
engineering one: it needs a real non-self-signed cert to matter to
external recipients (DESIGN.md).
"""
import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import signers
from pyhanko.sign.fields import SigFieldSpec
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext


def generate_self_signed_cert(key_path: str, cert_path: str, common_name="Slate Signer"):
    """A throwaway self-signed cert -- fine for internal sign-off, NOT a
    substitute for a real CA-issued signing certificate. A real cert+key
    can be supplied later with no other change -- load_signer() takes
    any PEM key/cert pair."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def load_signer(key_path: str, cert_path: str) -> signers.SimpleSigner:
    return signers.SimpleSigner.load(key_path, cert_path)


def sign(input_path: str, output_path: str, signer: signers.SimpleSigner, field_name="Signature1"):
    """PAdES-B-B baseline signature. Per DESIGN.md's sequencing
    constraint: this must be the LAST write to a document -- any further
    edit (redact/annotate/merge) after this invalidates the signature,
    since PDF signatures are append-only-incremental by design and cover
    everything up to the point they were added. Slate's UI layer (slice
    8) is responsible for warning/refusing further edits once
    is_signed() is true; this module only signs, it doesn't enforce
    that policy itself."""
    meta = signers.PdfSignatureMetadata(field_name=field_name)
    with open(input_path, "rb") as inf, open(output_path, "wb") as outf:
        w = IncrementalPdfFileWriter(inf)
        signers.sign_pdf(
            w, meta, signer=signer, new_field_spec=SigFieldSpec(field_name), output=outf
        )


def is_signed(path: str) -> bool:
    with open(path, "rb") as f:
        return len(PdfFileReader(f).embedded_signatures) > 0


def validate(path: str):
    """Returns a list of pyhanko validation status objects, one per
    embedded signature. Self-signed certs are validated by trusting the
    signer's own cert as the trust anchor -- appropriate for the self-
    signed v1 case, not for a real external cert chain."""
    results = []
    with open(path, "rb") as f:
        r = PdfFileReader(f)
        for sig in r.embedded_signatures:
            vc = ValidationContext(trust_roots=[sig.signer_cert], allow_fetching=False)
            results.append(validate_pdf_signature(sig, signer_validation_context=vc))
    return results
