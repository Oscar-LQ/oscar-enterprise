"""Unwrap w:sdt (Structured Document Tag) wrappers in OOXML elements.

Word and other editors sometimes wrap tracked changes inside w:sdt
elements. This module provides a generator that transparently
unwraps SDT containers, yielding the effective children regardless
of whether they are wrapped or not.

Source: claude-plugin-mcp/src/ingestion/sdt_unwrapper.py (verbatim).
See src/redline/lib/__init__.py for the package-level upgrade warning.
"""

from collections.abc import Iterator

from docx.oxml.ns import qn
from lxml import etree


def iter_effective_children(element: etree._Element) -> Iterator[etree._Element]:
    """Yield effective child elements, unwrapping w:sdt containers.

    For each direct child of the element:
    - If it is a w:sdt, yields the children of its w:sdtContent instead.
    - Otherwise, yields the child directly.

    SDT unwrapping is recursive: if an sdtContent itself contains
    another w:sdt, that is unwrapped too.

    Args:
        element: An lxml element whose children to iterate.

    Yields:
        Child elements with SDT wrappers transparently removed.
    """
    for child in element:
        if child.tag == qn("w:sdt"):
            sdt_content = child.find(qn("w:sdtContent"))
            if sdt_content is not None:
                yield from iter_effective_children(sdt_content)
        else:
            yield child
