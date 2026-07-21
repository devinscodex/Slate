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
