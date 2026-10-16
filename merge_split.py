"""Merge / split / reorder / extract pages. Thin wrappers over PyMuPDF's
own page-list operations -- no new logic needed, this library already
does this job well (DESIGN.md: compose, don't reimplement)."""
import fitz


def merge_pdfs(paths: list) -> fitz.Document:
    """Concatenate PDFs in order into one new in-memory document. Caller
    saves the result via io_pdf.safe_save."""
    out = fitz.open()
    for p in paths:
        with fitz.open(p) as src:
            out.insert_pdf(src)
    return out


def split_pdf(doc: fitz.Document) -> list:
    """One new single-page document per page of the input, same order."""
    docs = []
    for i in range(doc.page_count):
        one = fitz.open()
        one.insert_pdf(doc, from_page=i, to_page=i)
        docs.append(one)
    return docs


def extract_pages(doc: fitz.Document, page_nums: list) -> fitz.Document:
    """A new document containing only page_nums, in the given order
    (page_nums may repeat or reorder -- same page can appear twice)."""
    out = fitz.open()
    for i in page_nums:
        out.insert_pdf(doc, from_page=i, to_page=i)
    return out


def reorder_pages(doc: fitz.Document, new_order: list):
    """Reorder doc's pages in place. new_order must be a permutation of
    range(doc.page_count) -- every original page exactly once."""
    if sorted(new_order) != list(range(doc.page_count)):
        raise ValueError(
            "new_order must be a permutation of every existing page index"
        )
    doc.select(new_order)


def rotate_pages(doc: fitz.Document, page_nums: list, degrees: int):
    """Rotate each listed page by degrees (a multiple of 90, clockwise)."""
    if degrees % 90:
        raise ValueError("degrees must be a multiple of 90")
    for i in set(page_nums):
        page = doc[i]
        page.set_rotation((page.rotation + degrees) % 360)


def delete_pages(doc: fitz.Document, page_nums: list):
    """Delete the listed pages in place. A document cannot be emptied."""
    drop = set(page_nums)
    keep = [i for i in range(doc.page_count) if i not in drop]
    if not keep:
        raise ValueError("cannot delete every page")
    doc.select(keep)


def move_pages(doc: fitz.Document, page_nums: list, to_index: int):
    """Move the listed pages, kept in their current order, so the block
    starts at to_index among the pages that remain once the block is
    taken out (0 = front, page_count - len(block) = end)."""
    moving = sorted(set(page_nums))
    rest = [i for i in range(doc.page_count) if i not in moving]
    to_index = max(0, min(to_index, len(rest)))
    reorder_pages(doc, rest[:to_index] + moving + rest[to_index:])


def insert_pages(doc: fitz.Document, src: fitz.Document, at: int):
    """Insert every page of src into doc so the first lands at index at."""
    doc.insert_pdf(src, start_at=max(0, min(at, doc.page_count)))
