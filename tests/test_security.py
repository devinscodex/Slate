"""Slice 7 check: round-trip -- correct password opens, wrong password
fails, permission bits actually enforced (read back correctly)."""
import os
import sys

import fitz
import pikepdf
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import security  # noqa: E402


def _make_fixture(path):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "secured content", fontsize=14)
    doc.save(path)
    doc.close()


def test_correct_password_opens(tmp_path):
    src = str(tmp_path / "src.pdf")
    out = str(tmp_path / "enc.pdf")
    _make_fixture(src)
    security.encrypt(src, out, owner_password="ownerpw123", user_password="userpw123")

    with security.open_with_password(out, "userpw123") as pdf:
        assert len(pdf.pages) == 1
    with security.open_with_password(out, "ownerpw123") as pdf:
        assert len(pdf.pages) == 1


def test_wrong_password_fails(tmp_path):
    src = str(tmp_path / "src.pdf")
    out = str(tmp_path / "enc.pdf")
    _make_fixture(src)
    security.encrypt(src, out, owner_password="ownerpw123", user_password="userpw123")

    with pytest.raises(pikepdf.PasswordError):
        security.open_with_password(out, "totally-wrong-password")


def test_permission_bits_round_trip(tmp_path):
    """Restrict printing and modification, allow extraction; confirm
    every bit reads back exactly as set, not just 'some default'."""
    src = str(tmp_path / "src.pdf")
    out = str(tmp_path / "enc.pdf")
    _make_fixture(src)

    restricted = pikepdf.Permissions(
        accessibility=True,
        extract=True,
        modify_annotation=False,
        modify_assembly=False,
        modify_form=False,
        modify_other=False,
        print_lowres=False,
        print_highres=False,
    )
    security.encrypt(
        src, out, owner_password="ownerpw123", user_password="userpw123", allow=restricted
    )

    allow = security.get_permissions(out, "userpw123")
    assert allow.print_highres is False
    assert allow.print_lowres is False
    assert allow.modify_annotation is False
    assert allow.modify_assembly is False
    assert allow.modify_form is False
    assert allow.modify_other is False
    assert allow.extract is True
    assert allow.accessibility is True


def test_permissive_defaults_round_trip(tmp_path):
    """The other direction -- default Permissions() (everything allowed
    except assembly) also has to read back correctly, not just the
    restricted case above."""
    src = str(tmp_path / "src.pdf")
    out = str(tmp_path / "enc.pdf")
    _make_fixture(src)
    security.encrypt(src, out, owner_password="ownerpw123", user_password="userpw123")

    allow = security.get_permissions(out, "userpw123")
    assert allow.print_highres is True
    assert allow.extract is True
    assert allow.modify_annotation is True
