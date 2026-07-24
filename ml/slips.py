import base64, binascii, hashlib, io, json, os, re, threading
from datetime import datetime
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "ml" / "data" / "slips.json"
_STORE_LOCK = threading.RLock()
ROW = re.compile(
    r"(?P<datetime>\d{2}/\d{2}(?:/\d{2,4})?\s+\d{2}:\d{2})\s+"
    r"(?P<code>\d{5,})\s*:\s*Baseball\.?\s*(?:USA\.?\s*)?(?:MLB\.?\s*)?"
    r"(?P<event>(?:(?!\d{2}/\d{2}(?:/\d{2,4})?\s+\d{2}:\d{2})[\s\S])*?)\s+"
    r"(?P<selection>W[12])\s+(?P<odds>\d+(?:\.\d+)?)",
    re.I | re.S,
)
TOTAL_ROW = re.compile(
    r"(?P<datetime>\d{2}/\d{2}(?:/\d{2,4})?\s+\d{2}:\d{2})\s+"
    r"(?P<code>\d{5,})\s*:\s*Baseball\.?\s*(?:USA\.?\s*)?(?:MLB\.?\s*)?"
    r"(?P<event>.*?)\s+Total\s+(?P<side>Over|Under)\s*\(\s*(?P<line>\d+(?:\.\d+)?)\s*\)\s+"
    r"(?P<odds>\d+(?:\.\d+)?)",
    re.I | re.S,
)


def _number(pattern, text):
    match = re.search(pattern, text, re.I)
    return float(match.group(1)) if match else None


def placed_at_iso(placed_at, fallback=None, year=None):
    """Return a sortable local timestamp from the date printed on the slip."""
    if placed_at:
        for date_format in ("%d/%m/%Y %H:%M", "%d/%m/%y %H:%M"):
            try:
                return datetime.strptime(placed_at, date_format).isoformat()
            except ValueError:
                pass
        try:
            return datetime.strptime(f"{placed_at} {year or datetime.now().year}", "%d/%m %H:%M %Y").isoformat()
        except ValueError:
            pass
    return fallback


def _scheduled_datetime(value, year):
    has_year = value.count("/") == 2
    year_token = value.split()[0].split("/")[-1] if has_year else ""
    date_format = "%d/%m/%Y %H:%M" if len(year_token) == 4 else "%d/%m/%y %H:%M" if has_year else "%d/%m %H:%M %Y"
    return datetime.strptime(value if has_year else f"{value} {year}", date_format)


def _teams(event):
    return [part.strip() for part in re.split(r"\s+(?:-|–|—|vs\.?|v\.?)\s+", event, maxsplit=1, flags=re.I)]


def parse_selection_text(text, year):
    """Parse supported MelBet MLB rows while preserving their PDF order."""
    parsed = []
    for match in ROW.finditer(text):
        row = {key: " ".join(value.split()) for key, value in match.groupdict().items()}
        teams = _teams(row["event"])
        if len(teams) != 2:
            continue
        try:
            scheduled = _scheduled_datetime(row["datetime"], year)
        except ValueError:
            continue
        parsed.append((match.start(), {
            "event_code": row["code"], "scheduled_local": scheduled.isoformat(),
            "team_1": teams[0], "team_2": teams[1], "market": "moneyline", "selection": row["selection"],
            "selected_team": teams[0] if row["selection"].upper() == "W1" else teams[1],
            "slip_odds": float(row["odds"]), "game_id": None, "status": "unmatched",
            "outcome": "pending", "alerts": [],
        }))
    for match in TOTAL_ROW.finditer(text):
        row = {key: " ".join(value.split()) for key, value in match.groupdict().items()}
        teams = _teams(row["event"])
        if len(teams) != 2:
            continue
        try:
            scheduled = _scheduled_datetime(row["datetime"], year)
        except ValueError:
            continue
        side, line = row["side"].lower(), float(row["line"])
        line_label = f"{line:g}"
        parsed.append((match.start(), {
            "event_code": row["code"], "scheduled_local": scheduled.isoformat(),
            "team_1": teams[0], "team_2": teams[1], "market": "totals",
            "selection": f"Total {side.title()} ({line_label})", "total_side": side, "total_line": line,
            "selected_team": f"{side.title()} {line_label} total runs",
            "slip_odds": float(row["odds"]), "game_id": None, "status": "unmatched",
            "outcome": "pending", "alerts": [],
        }))
    return [selection for _, selection in sorted(parsed, key=lambda item: item[0])]


def parse_pdf(encoded, filename="slip.pdf"):
    try:
        payload = base64.b64decode(encoded.split(",")[-1], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("The uploaded file is not valid encoded PDF data.") from exc
    if not payload.startswith(b"%PDF"):
        raise ValueError("The selected file is not a PDF.")
    try:
        reader = PdfReader(io.BytesIO(payload))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise ValueError("The PDF is damaged, encrypted, or cannot be read.") from exc
    if not text.strip():
        raise ValueError("This PDF has no selectable text. Export a text-based slip PDF instead of a screenshot.")

    metadata = reader.metadata or {}
    created = str(metadata.get("/CreationDate", ""))
    year_match = re.search(r"(20\d{2})", created)
    year = int(year_match.group(1)) if year_match else datetime.now().year
    selections = []
    for match in ROW.finditer(text):
        row = {key: " ".join(value.split()) for key, value in match.groupdict().items()}
        teams = [part.strip() for part in re.split(r"\s+(?:-|–|—|vs\.?|v\.?)\s+", row["event"], maxsplit=1, flags=re.I)]
        if len(teams) != 2:
            continue
        try:
            has_year = row["datetime"].count("/") == 2
            year_token = row["datetime"].split()[0].split("/")[-1] if has_year else ""
            date_format = "%d/%m/%Y %H:%M" if len(year_token) == 4 else "%d/%m/%y %H:%M" if has_year else "%d/%m %H:%M %Y"
            date_value = row["datetime"] if has_year else f"{row['datetime']} {year}"
            parsed_date = datetime.strptime(date_value, date_format)
        except ValueError:
            continue
        selections.append({
            "event_code": row["code"], "scheduled_local": parsed_date.isoformat(),
            "team_1": teams[0], "team_2": teams[1], "market": "moneyline", "selection": row["selection"],
            "selected_team": teams[0] if row["selection"].upper() == "W1" else teams[1],
            "slip_odds": float(row["odds"]), "game_id": None, "status": "unmatched",
            "outcome": "pending", "alerts": [],
        })
    for match in TOTAL_ROW.finditer(text):
        row = {key: " ".join(value.split()) for key, value in match.groupdict().items()}
        teams = _teams(row["event"])
        if len(teams) != 2:
            continue
        try:
            parsed_date = _scheduled_datetime(row["datetime"], year)
        except ValueError:
            continue
        side, line = row["side"].lower(), float(row["line"])
        line_label = f"{line:g}"
        selections.append({
            "event_code": row["code"], "scheduled_local": parsed_date.isoformat(),
            "team_1": teams[0], "team_2": teams[1], "market": "totals",
            "selection": f"Total {side.title()} ({line_label})", "total_side": side, "total_line": line,
            "selected_team": f"{side.title()} {line_label} total runs",
            "slip_odds": float(row["odds"]), "game_id": None, "status": "unmatched",
            "outcome": "pending", "alerts": [],
        })
    selections.sort(key=lambda item: (item["scheduled_local"], item["event_code"]))
    if not selections:
        raise ValueError("No MLB moneyline (W1/W2) or full-game total selections were recognized. This slip layout may differ from the supported MelBet PDF format.")

    slip_match = re.search(r"Bet slip\s*(?:No\.?|#|№)?\s*(\d+)", text, re.I) or re.search(r"(\d{10,})", text)
    slip_id = slip_match.group(1) if slip_match else hashlib.sha1(payload).hexdigest()[:12]
    bet_type_match = re.search(r"Bet type:\s*([^\n]+)", text, re.I)
    placed_match = re.search(r"^(\d{2}/\d{2}(?:/\d{2,4})?\s+\d{2}:\d{2})", text, re.M)
    placed_at = placed_match.group(1) if placed_match else None
    return {
        "id": slip_id, "provider": "MelBet", "filename": filename,
        "bet_type": bet_type_match.group(1).strip() if bet_type_match else "Unknown",
        "placed_at": placed_at,
        "placed_at_iso": placed_at_iso(placed_at, year=year),
        "stake": _number(r"Overall\s*:\s*([\d.]+)", text),
        "currency": "ETB" if "ETB" in text else None,
        "overall_odds": _number(r"Overall odds:\s*([\d.]+)", text),
        "potential_winnings": _number(r"Potential winnings\s*:\s*([\d.]+)", text),
        "selections": selections, "imported_at": datetime.now().isoformat(),
        "source_text_length": len(text),
    }


def load_slips():
    with _STORE_LOCK:
        if not STORE.exists():
            return []
        return json.loads(STORE.read_text(encoding="utf-8"))


def save_slip(slip):
    with _STORE_LOCK:
        slips = [item for item in load_slips() if item["id"] != slip["id"]]
        slips.insert(0, slip)
        STORE.parent.mkdir(parents=True, exist_ok=True)
        temporary = STORE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(slips, indent=2), encoding="utf-8")
        os.replace(temporary, STORE)
    return slip


def normalize_team(value):
    value = re.sub(r"\bgame\s*[12]\b", "", value, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", value.lower().replace("st.", "saint"))
