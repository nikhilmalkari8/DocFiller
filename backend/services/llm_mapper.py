"""LLM-powered intelligent field mapper — supports OpenAI GPT and Google Gemini."""
import json
import os


def map_fields(
    excel_columns: list[str],
    placeholders: list[str],
    excel_preview: list[dict[str, str]] | None = None,
) -> dict[str, str]:
    """
    Use an LLM to intelligently map template placeholders to Excel columns.

    Tries providers in order: OpenAI (OPENAI_API_KEY) → Gemini (GEMINI_API_KEY) → fallback.

    Args:
        excel_columns: List of Excel column header names
        placeholders: List of placeholder names from the template (without << >> or «»)
        excel_preview: Optional preview rows for additional context

    Returns:
        Dict mapping each placeholder to the best-matching Excel column name.
        If no match, the value will be an empty string.
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    prompt = _build_prompt(excel_columns, placeholders, excel_preview)

    if openai_key:
        try:
            return _map_with_openai(openai_key, prompt, excel_columns, placeholders)
        except Exception as e:
            print(f"OpenAI mapping failed: {e}. Trying Gemini...")

    if gemini_key:
        try:
            return _map_with_gemini(gemini_key, prompt, excel_columns, placeholders)
        except Exception as e:
            print(f"Gemini mapping failed: {e}. Falling back to basic matching.")

    return _fallback_mapping(excel_columns, placeholders)


def _build_prompt(
    excel_columns: list[str],
    placeholders: list[str],
    excel_preview: list[dict[str, str]] | None,
) -> str:
    preview_context = ""
    if excel_preview and len(excel_preview) > 0:
        preview_context = (
            f"\n\nHere is a sample row of data from the Excel file for context:\n"
            f"{json.dumps(excel_preview[0], indent=2)}"
        )

    return f"""You are a data mapping assistant. Given a list of Excel column names and a list of document placeholder names, map each placeholder to the most appropriate Excel column.

Excel columns: {json.dumps(excel_columns)}

Document placeholders: {json.dumps(placeholders)}
{preview_context}

Rules:
- Each placeholder should be mapped to exactly one Excel column (or empty string if no match).
- Use semantic understanding: "Applicant Name" in the document should map to "Name" or "Full Name" in Excel.
- Be case-insensitive and flexible with naming variations.
- Return ONLY a valid JSON object with placeholder names as keys and Excel column names as values.

Example output format:
{{"Applicant Name": "Name", "Date of Birth": "DOB", "Loan Amount": "Amount"}}

Return ONLY the JSON, no explanation or markdown."""


def _parse_and_validate(
    response_text: str,
    excel_columns: list[str],
    placeholders: list[str],
) -> dict[str, str]:
    """Parse LLM JSON response and validate all mapped values are real column names."""
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    result = json.loads(text.strip())

    validated = {}
    for placeholder in placeholders:
        mapped_col = result.get(placeholder, "")
        if mapped_col in excel_columns:
            validated[placeholder] = mapped_col
        else:
            match = next(
                (c for c in excel_columns if c.lower() == str(mapped_col).lower()),
                "",
            )
            validated[placeholder] = match

    return validated


def _map_with_openai(
    api_key: str,
    prompt: str,
    excel_columns: list[str],
    placeholders: list[str],
) -> dict[str, str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return _parse_and_validate(
        response.choices[0].message.content or "",
        excel_columns,
        placeholders,
    )


def _map_with_gemini(
    api_key: str,
    prompt: str,
    excel_columns: list[str],
    placeholders: list[str],
) -> dict[str, str]:
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    return _parse_and_validate(response.text, excel_columns, placeholders)


def _fallback_mapping(
    excel_columns: list[str], placeholders: list[str]
) -> dict[str, str]:
    """
    Simple fallback mapping without LLM.
    Tries exact match, then case-insensitive, then substring matching.
    """
    result = {}
    col_lower_map = {c.lower().replace(" ", "").replace("_", ""): c for c in excel_columns}

    for placeholder in placeholders:
        ph_normalized = placeholder.lower().replace(" ", "").replace("_", "")

        if placeholder in excel_columns:
            result[placeholder] = placeholder
            continue

        if ph_normalized in col_lower_map:
            result[placeholder] = col_lower_map[ph_normalized]
            continue

        matched = ""
        for norm_col, orig_col in col_lower_map.items():
            if norm_col in ph_normalized or ph_normalized in norm_col:
                matched = orig_col
                break

        result[placeholder] = matched

    return result
