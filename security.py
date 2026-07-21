"""Encryption / password protection -- pikepdf-backed. Covers both
directions Slate needs (DESIGN.md, "IN v1"): opening PDFs Devin receives
that are already password-protected, and producing encrypted output.

Note pikepdf's own docs are explicit: the library does not enforce
permission restrictions itself -- it only encodes them in the file. A
compliant reader is expected to honor them. Slate's own UI layer (slice
8) is responsible for actually disabling e.g. printing when
`allow.print_highres` is False; this module's job is correctly setting
and reading back the bits, which is what's tested here.
"""
import pikepdf


def encrypt(
    input_path: str,
    output_path: str,
    owner_password: str,
    user_password: str,
    allow: pikepdf.Permissions = None,
):
    allow = allow or pikepdf.Permissions()
    with pikepdf.open(input_path) as pdf:
        pdf.save(
            output_path,
            encryption=pikepdf.Encryption(
                owner=owner_password, user=user_password, allow=allow
            ),
        )


def open_with_password(path: str, password: str) -> pikepdf.Pdf:
    """Raises pikepdf.PasswordError if the password is wrong."""
    return pikepdf.open(path, password=password)


def get_permissions(path: str, password: str) -> pikepdf.Permissions:
    with open_with_password(path, password) as pdf:
        return pdf.allow
