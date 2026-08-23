"""PDF template processor — extract placeholders and fill them."""
import re
import pymupdf  # PyMuPDF
from io import BytesIO
from typing import Any


PLACEHOLDER_PATTERN = re.compile(r"<<(.+?)>>")


def extract_placeholders(file_bytes: bytes) -> list[str]:
    """
    Scan all pages of a PDF for <<placeholder>> patterns.
    Returns a unique list of placeholder names (without the << >>).
    """
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    placeholders = set()

    for page in doc:
        text = page.get_text("text")
        matches = PLACEHOLDER_PATTERN.findall(text)
        for m in matches:
            placeholders.add(m.strip())

    doc.close()
    return sorted(placeholders)


def _get_font_info(page, rect) -> dict[str, Any]:
    """
    Extract font properties (name, size, color) from text within a rect.
    Falls back to sensible defaults if extraction fails.
    """
    defaults = {"fontname": "helv", "fontsize": 11.0, "color": (0, 0, 0)}

    try:
        # Get detailed text info at the placeholder location
        text_dict = page.get_text("dict", clip=rect, flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if "<<" in span.get("text", ""):
                        # Extract color from integer
                        color_int = span.get("color", 0)
                        r = ((color_int >> 16) & 0xFF) / 255.0
                        g = ((color_int >> 8) & 0xFF) / 255.0
                        b = (color_int & 0xFF) / 255.0
                        return {
                            "fontname": "helv",  # Use standard font for reliability
                            "fontsize": span.get("size", 11.0),
                            "color": (r, g, b),
                        }
    except Exception:
        pass

    return defaults


def fill_pdf(file_bytes: bytes, mapping: dict[str, str]) -> bytes:
    """
    Fill a PDF template by replacing <<placeholder>> with actual values.
    
    Args:
        file_bytes: Original PDF bytes
        mapping: Dict of {placeholder_name: value_to_fill}
    
    Returns:
        Filled PDF as bytes
    """
    doc = pymupdf.open(stream=file_bytes, filetype="pdf")

    for page in doc:
        for placeholder_name, value in mapping.items():
            search_text = f"<<{placeholder_name}>>"
            
            # Find all instances of this placeholder on this page
            instances = page.search_for(search_text)
            
            for rect in instances:
                # 1. Capture font info before redacting
                font_info = _get_font_info(page, rect)

                # 2. Redact the placeholder text
                page.add_redact_annot(
                    rect,
                    text="",  # Remove the text
                    fill=(1, 1, 1),  # White fill to cover
                )
                page.apply_redactions()

                # 3. Insert the replacement value at the same position
                # Use the top-left of the rect as insertion point,
                # adjusted slightly down to align with baseline
                insert_point = pymupdf.Point(rect.x0, rect.y1 - 2)
                
                page.insert_text(
                    insert_point,
                    str(value),
                    fontname=font_info["fontname"],
                    fontsize=font_info["fontsize"],
                    color=font_info["color"],
                )

    # Save to bytes
    output = BytesIO()
    doc.save(output)
    doc.close()
    
    return output.getvalue()
