import math
import hashlib
import json
import re
import urllib.parse
import uuid
from datetime import datetime, timezone

from taskvault_catalog import currency, get_product, index_meta, load_catalog


GENERIC_ALIASES = {
    "gloves", "glove", "examination gloves", "exam gloves", "medical gloves",
    "syringes", "syringe", "needles", "masks", "mask", "gowns", "gown",
    "tablets", "tablet", "bottles", "bottle", "units", "unit",
}

RESEARCH_WORDS = {
    "find", "source", "sourcing", "supplier", "suppliers", "vendor", "vendors",
    "compare", "comparison", "price", "prices", "quote", "quotation", "order",
    "buy", "procure", "procurement", "moq", "stock", "distributor", "wholesale",
    "landed", "delivery", "lead", "cheapest", "best",
}

UNIT_WORDS = {
    "box": "unit", "boxes": "unit", "pack": "unit", "packs": "unit",
    "case": "unit", "cases": "unit", "carton": "carton", "cartons": "carton",
    "unit": "piece", "units": "piece", "piece": "piece", "pieces": "piece",
    "pcs": "piece", "pc": "piece", "glove": "piece", "gloves": "piece",
    "mask": "piece", "masks": "piece", "tablet": "piece", "tablets": "piece",
    "bottle": "piece", "bottles": "piece",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def parse_number(value):
    return int(str(value).replace(",", ""))


def plural_unit(unit, count):
    unit = str(unit or "unit").strip()
    if not unit:
        unit = "unit"
    if " of " in unit:
        head, _, _tail = unit.partition(" of ")
        return {"box": "boxes", "case": "cases", "carton": "cartons"}.get(head, head + "s")
    if unit.endswith("s"):
        return unit
    if count == 1:
        return unit
    return unit + "s"


def match_product(text):
    normalized = normalize_text(text)
    best = None
    best_score = 0
    for product in load_catalog().get("products", []):
        score = 0
        for alias in product.get("aliases", []):
            lowered = alias.lower()
            pattern = r"(?<![a-z0-9])" + re.escape(lowered) + r"(?![a-z0-9])"
            if re.search(pattern, normalized):
                score += 1 if lowered in GENERIC_ALIASES else len(alias) + (8 if " " in alias else 0)
        if score > best_score:
            best = product
            best_score = score
    return best


def resolve_product(text):
    product = match_product(text)
    if product:
        return product
    normalized = re.sub(r"[.?!]+$", "", normalize_text(text)).strip()
    match = re.search(
        r"(?:source|find|compare|procure|order|buy|get)?\s*(?:\d[\d,]*\s*(?:boxes?|cartons?|cases?|packs?|units?|pcs?|pieces?)\s*(?:of\s+)?)(?P<item>[a-z0-9][a-z0-9\s\-_/]+?)(?:\s+(?:from|at|under|with|for|via|within|\.|\?|$)|$)",
        normalized,
        re.IGNORECASE,
    )
    if match:
        item = match.group("item").strip()
        if item and len(item) >= 3 and item not in GENERIC_ALIASES:
            key = re.sub(r"[^a-z0-9]+", "-", item).strip("-")
            name = item.title()
            return {
                "key": key or "custom-product",
                "name": name,
                "short_name": name,
                "unit": "unit",
                "pack_size": 1,
                "carton_size": 1,
                "specs": "",
                "image": "",
                "aliases": [item],
                "offers": [],
            }
    return None


def is_research_request(text):
    product = resolve_product(text)
    if not product:
        return False
    words = set(re.findall(r"[a-z]+", normalize_text(text)))
    return bool(words & RESEARCH_WORDS) or bool(
        re.search(r"\d[\d,]*\s*(boxes?|cartons?|cases?|packs?|units?|pcs?|pieces?)", normalize_text(text))
    )


def has_explicit_quantity(text):
    return bool(re.search(
        r"\b\d[\d,]*\s*(?:boxes?|cartons?|cases?|packs?|units?|pcs?|pieces?|gloves?|masks?|tablets?|bottles?)\b",
        normalize_text(text),
    ))


def extract_quantity(text, product):
    normalized = normalize_text(text)
    match = re.search(
        r"(?P<count>\d[\d,]*)\s*(?P<unit>boxes?|cartons?|cases?|packs?|units?|pcs?|pieces?|gloves?|masks?|tablets?|bottles?)",
        normalized,
    )
    if not match:
        raise ValueError("Specify an order quantity and unit, such as 500 boxes.")

    count = parse_number(match.group("count"))
    unit_word = match.group("unit")
    kind = UNIT_WORDS.get(unit_word, "piece")
    pack_size = max(1, int(product.get("pack_size", 1) or 1))
    carton_size = max(1, int(product.get("carton_size", 1) or 1))
    note = ""
    if kind == "carton":
        units = count * carton_size
        note = "{} cartons converted at {} units per carton.".format(count, carton_size)
    elif kind == "piece":
        units = int(math.ceil(count / pack_size))
        note = "{} pieces converted at {} pieces per unit.".format(count, pack_size)
    else:
        units = count
    units = max(1, min(units, 100000))
    label_unit = plural_unit(product.get("unit", "unit"), units)
    return {
        "requested_units": units,
        "input_count": count,
        "input_unit": unit_word,
        "quantity_label": "{} {}".format(units, label_unit),
        "quantity_note": note,
    }


def _normalize(value, low, high):
    if high <= low:
        return 0.0
    return (value - low) / (high - low)


def compute_offers(product, requested_units):
    offers = []
    is_demo = bool(index_meta().get("is_demo"))
    raw_offers = product.get("offers", [])
    for raw in raw_offers:
        moq = int(raw.get("moq_boxes", 1) or 1)
        order_units = max(requested_units, moq)
        unit_price = float(raw.get("unit_price", 0) or 0)
        subtotal = round(unit_price * order_units, 2)
        threshold = float(raw.get("free_shipping_threshold", 0) or 0)
        shipping = 0.0 if threshold and subtotal >= threshold else float(raw.get("shipping_flat", 0) or 0)
        landed = round(subtotal + shipping, 2)
        offers.append(
            {
                "id": raw["id"],
                "product_key": product["key"],
                "product_name": product["name"],
                "product_short_name": product.get("short_name", product["name"]),
                "supplier": raw["supplier"],
                "supplier_slug": raw.get("supplier_slug", ""),
                "location": raw.get("location", ""),
                "unit": product.get("unit", "unit"),
                "pack_size": int(product.get("pack_size", 1) or 1),
                "unit_price": round(unit_price, 2),
                "previous_price": raw.get("previous_price"),
                "requested_units": requested_units,
                "order_units": order_units,
                "moq_units": moq,
                "moq_label": "{} {}".format(moq, plural_unit(product.get("unit", "unit"), moq)),
                "moq_met": requested_units >= moq,
                "subtotal": subtotal,
                "shipping": round(shipping, 2),
                "free_shipping": shipping == 0,
                "landed_cost": landed,
                "landed_unit_price": round(landed / order_units, 2) if order_units else 0,
                "lead_time_days": int(raw.get("lead_time_days", 0) or 0),
                "rating": float(raw.get("rating", 0) or 0),
                "reviews": int(raw.get("reviews", 0) or 0),
                "verified": bool(raw.get("verified")),
                "verification_status": "illustrative_sample" if is_demo else "verified" if raw.get("verified") else "listing_only",
                "certifications": list(raw.get("certifications", [])),
                "return_window_days": int(raw.get("return_window_days", 0) or 0),
                "image_url": product.get("image", ""),
                "source_url": "/sources/{}".format(raw["id"]),
                "source_title": raw.get("source_title", "{} listing".format(raw["supplier"])),
                "captured_at": raw.get("updated_at", utc_now()),
                "highlights": list(raw.get("highlights", [])),
                "specs": product.get("specs", ""),
                "currency": "USD",
            }
        )

    if not offers:
        return []

    min_landed = min(offer["landed_cost"] for offer in offers)
    max_landed = max(offer["landed_cost"] for offer in offers)
    min_lead = min(offer["lead_time_days"] for offer in offers)
    max_lead = max(offer["lead_time_days"] for offer in offers)
    max_moq = max(offer["moq_units"] for offer in offers)

    weights = {
        "landed_cost": 0.46,
        "lead_time": 0.22,
        "rating": 0.18,
        "minimum_order": 0.06,
        "verification": 0.08,
    }
    for offer in offers:
        cost_norm = _normalize(offer["landed_cost"], min_landed, max_landed)
        lead_norm = _normalize(offer["lead_time_days"], min_lead, max_lead)
        rating_penalty = (5.0 - offer["rating"]) / 5.0
        moq_norm = offer["moq_units"] / max_moq if max_moq else 0
        verification_penalty = 0.0 if offer["verified"] else 1.0
        components = {
            "landed_cost": cost_norm * weights["landed_cost"],
            "lead_time": lead_norm * weights["lead_time"],
            "rating": rating_penalty * weights["rating"],
            "minimum_order": moq_norm * weights["minimum_order"],
            "verification": verification_penalty * weights["verification"],
        }
        offer["score_breakdown"] = {
            "components": components,
            "total_penalty": round(sum(components.values()), 4),
            "method": "weighted_penalty_v1",
        }
        offer["score"] = round(
            sum(components.values()),
            4,
        )
        offer["movement"] = _movement(offer)
        offer["badges"] = []

    ranked = sorted(offers, key=lambda item: (item["score"], item["landed_cost"]))
    for index, offer in enumerate(ranked, start=1):
        offer["rank"] = index

    best_value = ranked[0]
    cheapest = min(offers, key=lambda item: (item["landed_cost"], item["score"]))
    fastest = min(offers, key=lambda item: (item["lead_time_days"], item["landed_cost"]))
    highest = max(offers, key=lambda item: item["landed_cost"])
    average = sum(item["landed_cost"] for item in offers) / len(offers)

    best_value["badges"].append("Best overall")
    cheapest["badges"].append("Lowest landed cost")
    fastest["badges"].append("Fastest dispatch")
    for offer in offers:
        if not offer["verified"]:
            offer["badges"].append("Documentation pending")
        if not offer["moq_met"]:
            offer["badges"].append("Below MOQ")
        offer["badges"] = list(dict.fromkeys(offer["badges"]))
        offer["reasons"] = _reasons(offer, best_value, cheapest, fastest, is_demo)
        offer["evidence"] = {
            "source_url": offer["source_url"],
            "source_title": offer["source_title"],
            "captured_at": offer["captured_at"],
            "claims": [
                {"field": "unit_price", "value": offer["unit_price"], "status": offer["verification_status"]},
                {"field": "moq_units", "value": offer["moq_units"], "status": offer["verification_status"]},
                {"field": "lead_time_days", "value": offer["lead_time_days"], "status": offer["verification_status"]},
            ],
        }
        digest_payload = {
            "offer_id": offer["id"],
            "source_url": offer["source_url"],
            "claims": offer["evidence"]["claims"],
            "order_units": offer["order_units"],
            "landed_cost": offer["landed_cost"],
            "score": offer["score"],
            "score_breakdown": offer["score_breakdown"],
            "verification_status": offer["verification_status"],
        }
        offer["evidence"]["record_sha256"] = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    return {
        "offers": ranked,
        "ranking_method": {
            "id": "weighted_penalty_v1",
            "description": "Lowest weighted penalty ranks first; cost, lead time, rating, MOQ, and documentation contribute using fixed weights.",
            "weights": weights,
            "tie_break": "lower landed cost",
        },
        "best_value_id": best_value["id"],
        "cheapest_id": cheapest["id"],
        "fastest_id": fastest["id"],
        "highest_id": highest["id"],
        "savings_vs_highest": round(highest["landed_cost"] - best_value["landed_cost"], 2),
        "savings_vs_average": round(average - best_value["landed_cost"], 2),
    }


def _movement(offer):
    previous = offer.get("previous_price")
    if not previous:
        return None
    try:
        previous = float(previous)
    except (TypeError, ValueError):
        return None
    current = float(offer["unit_price"])
    if previous <= 0 or current == previous:
        return None
    change = round(((current - previous) / previous) * 100, 1)
    return {
        "previous_price": round(previous, 2),
        "current_price": current,
        "percent": change,
        "direction": "down" if change < 0 else "up",
    }


def _reasons(offer, best_value, cheapest, fastest, is_demo=False):
    reasons = []
    if offer["id"] == best_value["id"]:
        reasons.append("Best balance of landed cost, speed, rating, and documentation status" if not is_demo else "Best balance in the illustrative sample ranking")
    if offer["id"] == cheapest["id"]:
        reasons.append("Lowest landed cost in this comparison")
    if offer["id"] == fastest["id"]:
        reasons.append("Fastest dispatch at {} days".format(offer["lead_time_days"]))
    if is_demo:
        reasons.append("Illustrative supplier-documentation flag; no external verification was performed")
    elif offer["verified"]:
        reasons.append("Supplier documentation verified in the index")
    else:
        reasons.append("Supplier documentation has not been verified")
    if offer["free_shipping"]:
        reasons.append("Shipping included at this quantity")
    if offer["moq_met"]:
        reasons.append("Meets the requested quantity")
    else:
        reasons.append("Minimum order adjusted to {} units".format(offer["moq_units"]))
    return reasons


def _money(value):
    return "${:,.2f}".format(float(value or 0))


def build_summary(product, quantity, offers_payload, buyer=None):
    offers = offers_payload["offers"]
    best = next(offer for offer in offers if offer["id"] == offers_payload["best_value_id"])
    cheapest = next(offer for offer in offers if offer["id"] == offers_payload["cheapest_id"])
    fastest = next(offer for offer in offers if offer["id"] == offers_payload["fastest_id"])
    verified = [offer for offer in offers if offer["verified"]]
    unverified = [offer for offer in offers if not offer["verified"]]
    is_demo = bool(index_meta().get("is_demo"))
    first_line = (
        "I compared {} illustrative sample records for {} of {}." if is_demo
        else "I checked {} supplier listings for {} of {}."
    )
    lines = [
        first_line.format(len(offers), quantity["quantity_label"], product["name"].lower()),
        "{} is the best overall balance at {} landed ({} per {}), with a {}.".format(
            best["supplier"],
            _money(best["landed_cost"]),
            _money(best["landed_unit_price"]),
            best["unit"],
            _lead_phrase(best["lead_time_days"]),
        ),
    ]
    if cheapest["id"] != best["id"]:
        cheapest_note = "{} has the lowest landed cost at {}.".format(cheapest["supplier"], _money(cheapest["landed_cost"]))
        if is_demo:
            cheapest_note += " Its sample verification flag is illustrative only."
        elif not cheapest["verified"]:
            cheapest_note += " That listing still needs documentation checks."
        lines.append(cheapest_note)
    if fastest["id"] not in (best["id"], cheapest["id"]):
        lines.append(
            "{} is the fastest option at {}.".format(fastest["supplier"], _day_label(fastest["lead_time_days"]))
        )
    if is_demo:
        lines.append("{} of {} sample records have an illustrative verification flag; no supplier or document was checked.".format(len(verified), len(offers)))
    elif unverified:
        lines.append("{} of {} listings have supplier documentation marked verified; the rest are listing-only and should not be treated as approved vendors.".format(len(verified), len(offers)))
    if buyer and buyer.get("ship_to"):
        lines.append("Landed cost is estimated for delivery to {} and excludes tax.".format(buyer["ship_to"]))
    else:
        lines.append("Landed cost includes the listed shipping estimate and excludes tax.")
    lines.append("No message was sent, no order was placed, and nothing was paid.")
    return " ".join(lines)


def _day_label(days):
    return "{} day{}".format(days, "" if days == 1 else "s")


def _lead_phrase(days):
    return "{}-day lead time".format(days)


def recommendation_text(product, quantity, offers_payload):
    offers = offers_payload["offers"]
    best = next(offer for offer in offers if offer["id"] == offers_payload["best_value_id"])
    alternatives = [offer for offer in offers if offer["id"] != best["id"]]
    parts = [
        "Recommended: {}".format(best["supplier"]),
        "{} landed for {}".format(_money(best["landed_cost"]), quantity["quantity_label"]),
        "Sample verification flag: {}".format("yes" if best["verified"] else "no")
        if index_meta().get("is_demo") else "Verified: {}".format("yes" if best["verified"] else "no"),
    ]
    if alternatives:
        cheaper_alt = min(alternatives, key=lambda offer: offer["landed_cost"])
        if cheaper_alt["landed_cost"] < best["landed_cost"]:
            parts.append(
                "{} is {} cheaper, but ranks lower on speed or verification".format(
                    cheaper_alt["supplier"],
                    _money(best["landed_cost"] - cheaper_alt["landed_cost"]),
                )
            )
        faster_alt = min(alternatives, key=lambda offer: offer["lead_time_days"])
        if faster_alt["lead_time_days"] < best["lead_time_days"]:
            parts.append("{} ships in {}".format(faster_alt["supplier"], _day_label(faster_alt["lead_time_days"])))
    if best["id"] == offers_payload["cheapest_id"]:
        parts.append("It is also the lowest landed cost")
    return " · ".join(parts)


def _capture_supplier_name(capture):
    title = str(capture.get("title") or "").strip()
    if title:
        head = re.split(r"\s+(?:\-|:|·|\|)\s+", title)[0].strip()
        if len(head) >= 3:
            return head[:120]
    parsed = urllib.parse.urlsplit(capture.get("final_url") or capture.get("url") or "")
    host = parsed.hostname or capture.get("host") or ""
    parts = [chunk for chunk in host.split(".") if chunk and chunk not in ("www", "m", "shop")]
    return (parts[0].replace("-", " ").title() if parts else "Captured supplier")[:120]


def _extract_first_number(text, pattern):
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    for group in match.groups():
        if group:
            try:
                return float(str(group).replace(",", ""))
            except ValueError:
                return None
    return None


def _live_offers_from_captures(product, quantity, browser_payload):
    offers = []
    captures = list(browser_payload.get("captures") or [])
    for index, capture in enumerate(captures, start=1):
        if not isinstance(capture, dict):
            continue
        text = str(capture.get("text_excerpt") or "")
        unit_price = _extract_first_number(text, r"(?:usd|\$)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
        moq = _extract_first_number(text, r"(?:moq|minimum order)\D{0,16}([0-9][0-9,]*)")
        lead = _extract_first_number(text, r"([0-9]{1,3})\s*(?:-|to)?\s*[0-9]{0,3}\s*(?:business\s+)?days?")
        requested_units = quantity["requested_units"]
        minimum_units = int(moq or 1)
        order_units = max(requested_units, minimum_units)
        has_price = unit_price is not None and unit_price > 0
        effective_unit_price = round(float(unit_price), 2) if has_price else 999999.0
        landed_cost = round(effective_unit_price * order_units, 2)
        final_url = capture.get("final_url") or capture.get("url") or ""
        offer = {
            "id": "live-{}-{}".format(index, uuid.uuid4().hex[:6]),
            "product_key": product["key"],
            "product_name": product["name"],
            "product_short_name": product.get("short_name", product["name"]),
            "supplier": _capture_supplier_name(capture),
            "supplier_slug": "",
            "location": "Unknown",
            "unit": product.get("unit", "unit"),
            "pack_size": int(product.get("pack_size", 1) or 1),
            "unit_price": effective_unit_price,
            "price_known": has_price,
            "previous_price": None,
            "requested_units": requested_units,
            "order_units": order_units,
            "moq_units": minimum_units,
            "moq_label": "{} {}".format(minimum_units, plural_unit(product.get("unit", "unit"), minimum_units)),
            "moq_met": requested_units >= minimum_units,
            "subtotal": landed_cost,
            "shipping": 0.0,
            "free_shipping": False,
            "landed_cost": landed_cost,
            "landed_unit_price": round(landed_cost / order_units, 2) if order_units else 0,
            "lead_time_days": int(lead or 0),
            "rating": 0,
            "reviews": 0,
            "verified": False,
            "verification_status": "captured_unverified",
            "certifications": [],
            "return_window_days": 0,
            "image_url": product.get("image", ""),
            "source_url": final_url,
            "source_title": capture.get("title") or "Captured source",
            "captured_at": capture.get("captured_at") or utc_now(),
            "highlights": ["Read-only browser capture", "Extraction may be partial"],
            "specs": product.get("specs", ""),
            "currency": "USD",
            "capture_error": capture.get("error"),
        }
        offer["evidence"] = {
            "source_url": final_url,
            "source_title": offer["source_title"],
            "captured_at": offer["captured_at"],
            "screenshot_file": capture.get("screenshot_file"),
            "screenshot_sha256": capture.get("screenshot_sha256"),
            "text_sha256": capture.get("text_sha256"),
            "claims": [
                {"field": "unit_price", "value": unit_price, "status": "captured" if has_price else "unknown"},
                {"field": "moq_units", "value": minimum_units, "status": "captured" if moq else "unknown"},
                {"field": "lead_time_days", "value": int(lead or 0), "status": "captured" if lead else "unknown"},
            ],
        }
        offers.append(offer)

    offers.sort(key=lambda offer: (
        0 if offer.get("price_known") else 1,
        offer.get("landed_cost", 0),
        offer.get("lead_time_days", 9999),
    ))
    for rank, offer in enumerate(offers, start=1):
        offer["rank"] = rank
        offer["score"] = rank
        offer["score_breakdown"] = {
            "method": "live_capture_v1",
            "components": {
                "missing_price_penalty": 1 if not offer.get("price_known") else 0,
                "rank_penalty": rank,
            },
            "total_penalty": rank + (1 if not offer.get("price_known") else 0),
        }
        badges = ["Live capture"]
        if not offer.get("price_known"):
            badges.append("Price missing")
        if offer.get("capture_error"):
            badges.append("Capture warning")
        offer["badges"] = badges
        offer["reasons"] = [
            "Observed from a read-only browser capture.",
            "Supplier documentation is not yet verified.",
        ]
    return offers


def run_live_research(query, browser_payload, buyer=None, sources=None):
    product = resolve_product(query)
    if not product:
        raise ValueError("Name a product to source, for example nitrile gloves or 5 mL syringes.")
    quantity = extract_quantity(query, product)
    offers = _live_offers_from_captures(product, quantity, browser_payload)
    if not offers:
        raise ValueError("No captures were available for this sourcing request.")
    priced = [offer for offer in offers if offer.get("price_known")]
    best = priced[0] if priced else offers[0]
    fastest = min(offers, key=lambda offer: offer.get("lead_time_days", 9999))

    lines = [
        "I captured {} source page(s) in read-only browser mode for {} of {}.".format(
            len(browser_payload.get("captures") or []), quantity["quantity_label"], product["name"].lower()
        )
    ]
    if priced:
        lines.append(
            "{} currently has the lowest extracted unit price at {} per {}, with estimated landed cost {} for this quantity.".format(
                best["supplier"], _money(best["unit_price"]), best["unit"], _money(best["landed_cost"])
            )
        )
    else:
        lines.append("I could not extract reliable numeric pricing from the captured pages yet.")
    lines.append(
        "{} appears fastest at {}. Missing fields remain unknown until confirmed in writing with each supplier.".format(
            fastest["supplier"], _day_label(fastest.get("lead_time_days", 0) or 0)
        )
    )
    lines.append("No message was sent, no order was placed, and nothing was paid.")

    recommendation = (
        "Recommended next step: review the captures and request confirmed written quotes from {} first.".format(best["supplier"])
        if priced else
        "Recommended next step: open each capture and request a confirmed written quote before ranking by price."
    )

    return {
        "product": {
            "key": product["key"],
            "name": product["name"],
            "short_name": product.get("short_name", product["name"]),
            "unit": product.get("unit", "unit"),
            "specs": product.get("specs", ""),
            "image": product.get("image", ""),
        },
        "requested_units": quantity["requested_units"],
        "quantity": quantity,
        "currency": "USD",
        "offers": offers,
        "ranking_method": {
            "id": "live_capture_v1",
            "description": "Offers with extracted price rank first by landed estimate; captures without numeric price are ranked after priced offers.",
            "weights": {"price_known": 1.0, "landed_cost": 1.0, "lead_time_days": 0.5},
            "tie_break": "faster lead time",
        },
        "best_value_id": best["id"],
        "cheapest_id": best["id"] if priced else None,
        "fastest_id": fastest["id"],
        "savings_vs_highest": None,
        "savings_vs_average": None,
        "verified_count": 0,
        "evidence_count": len(browser_payload.get("captures") or []),
        "summary": " ".join(lines),
        "recommendation": recommendation,
        "limitations": [
            "Live capture extraction is best-effort and can miss or misread fields.",
            "Unverified fields remain unknown and must be confirmed directly with suppliers.",
            "No external action has been taken.",
        ],
        "user_sources": list(sources or []),
        "captures": browser_payload.get("captures") or [],
        "capture_report": {
            "requested_count": browser_payload.get("requested_count", 0),
            "captured_count": browser_payload.get("captured_count", 0),
            "error_count": browser_payload.get("error_count", 0),
            "blocked_requests": browser_payload.get("blocked_requests", []),
        },
        "index": {"is_demo": False, "version": "live-capture-v1"},
        "generated_at": utc_now(),
    }


def run_research(query, buyer=None, sources=None):
    product = resolve_product(query)
    if not product:
        raise ValueError("Name a product to source, for example nitrile gloves or 5 mL syringes.")
    quantity = extract_quantity(query, product)
    offers_payload = compute_offers(product, quantity["requested_units"])
    if not offers_payload:
        if sources:
            offers_payload = {
                "offers": [],
                "ranking_method": {"id": "pending_live_capture", "description": "Awaiting live capture offers", "weights": {}, "tie_break": ""},
                "best_value_id": None,
                "cheapest_id": None,
                "fastest_id": None,
                "savings_vs_highest": None,
                "savings_vs_average": None,
            }
        else:
            raise ValueError("No supplier listings are available for that product yet.")
    summary = build_summary(product, quantity, offers_payload, buyer=buyer) if offers_payload.get("offers") else "Awaiting live source capture."
    recommendation = recommendation_text(product, quantity, offers_payload) if offers_payload.get("offers") else "Capturing evidence from source pages."
    verified_count = sum(1 for offer in offers_payload["offers"] if offer["verified"])
    index = index_meta()
    if index.get("is_demo"):
        summary = (
            "DEMONSTRATION DATA ONLY. Supplier names, prices, ratings, certifications, and status flags are illustrative, not verified buying evidence. "
            + summary
        )
        recommendation = "Illustrative sample ranking only · " + recommendation
    return {
        "product": {
            "key": product["key"],
            "name": product["name"],
            "short_name": product.get("short_name", product["name"]),
            "unit": product.get("unit", "unit"),
            "specs": product.get("specs", ""),
            "image": product.get("image", ""),
        },
        "requested_units": quantity["requested_units"],
        "quantity": quantity,
        "currency": currency(),
        "offers": offers_payload["offers"],
        "ranking_method": offers_payload["ranking_method"],
        "best_value_id": offers_payload["best_value_id"],
        "cheapest_id": offers_payload["cheapest_id"],
        "fastest_id": offers_payload["fastest_id"],
        "savings_vs_highest": offers_payload["savings_vs_highest"],
        "savings_vs_average": offers_payload["savings_vs_average"],
        "verified_count": verified_count,
        "evidence_count": len(offers_payload["offers"]),
        "summary": summary,
        "recommendation": recommendation,
        "limitations": [
            "Landed cost includes the listed shipping estimate and excludes tax.",
            "Supplier ratings are index ratings, not a guarantee of future performance.",
            "Prices and availability should be re-confirmed in a quote before ordering.",
        ],
        "user_sources": list(sources or []),
        "index": index,
        "generated_at": utc_now(),
    }


def compact_context(payload, limit=6):
    offers = payload.get("offers", [])[:limit]
    return {
        "product": payload.get("product", {}).get("name"),
        "quantity": payload.get("quantity", {}).get("quantity_label"),
        "best_value": payload.get("best_value_id"),
        "is_demo": bool(payload.get("index", {}).get("is_demo")),
        "currency": payload.get("currency", "USD"),
        "offers": [
            {
                "supplier": offer.get("supplier"),
                "unit_price": offer.get("unit_price"),
                "landed_cost": offer.get("landed_cost"),
                "moq_units": offer.get("moq_units"),
                "lead_time_days": offer.get("lead_time_days"),
                "rating": offer.get("rating"),
                "verified": offer.get("verified"),
            }
            for offer in offers
        ],
    }


def build_narrative_messages(payload, buyer=None):
    context = compact_context(payload)
    system = (
        "You are TaskVault, a careful procurement assistant. You write concise, factual "
        "procurement summaries from the supplied structured offer data only. Never invent supplier "
        "names, prices, stock, ratings, delivery times, certifications, links, or completed actions. "
        "Never claim to have browsed a live supplier website; the data comes from a bounded sourcing "
        "run. Mention when a listing is listing-only or unverified. Do not claim to have sent a "
        "message, placed an order, or paid. End with the next safe action, usually reviewing evidence "
        "or requesting approval for a quote."
    )
    user = (
        "Write a short sourcing summary (120-170 words) with a clear recommendation and one trade-off. "
        "Use the currency in the structured data. If is_demo is true, clearly say that all supplier details, prices, ratings, documentation flags, and rankings are illustrative and not buying evidence. "
        "Structured data:\n" + str(context)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def answer_from_result(question, payload, buyer=None):
    normalized = normalize_text(question)
    offers = payload.get("offers", [])
    if not offers:
        return {
            "answer": "There is no completed supplier comparison yet. Start a sourcing task first.",
            "links": [],
        }
    best = next((offer for offer in offers if offer["id"] == payload.get("best_value_id")), offers[0])
    priced = [offer for offer in offers if offer.get("price_known", True)]
    cheapest = min(priced or offers, key=lambda offer: offer["landed_cost"])
    fastest = min(offers, key=lambda offer: offer["lead_time_days"])
    lowest_moq = min(offers, key=lambda offer: offer["moq_units"])
    if any(word in normalized for word in ("cheapest", "lowest price", "least expensive", "cost")):
        if not priced:
            answer = "I could not extract a reliable numeric price from the captured evidence yet. Open the captures and request written quotes to compare landed cost safely."
        else:
            offer = cheapest
            answer = "{} has the lowest landed cost at {}, or {} per {}. {}".format(
                offer["supplier"],
                _money(offer["landed_cost"]),
                _money(offer["landed_unit_price"]),
                offer["unit"],
                "That listing is not fully verified yet." if not offer["verified"] else "Its supplier documentation is verified.",
            )
    elif any(word in normalized for word in ("fastest", "delivery", "lead time", "quickest", "ship")):
        offer = fastest
        answer = "{} is the fastest option, with a {} and {} landed cost.".format(
            offer["supplier"], _lead_phrase(offer["lead_time_days"]), _money(offer["landed_cost"])
        )
    elif any(word in normalized for word in ("minimum", "moq", "minimum order")):
        offer = lowest_moq
        answer = "{} has the lowest minimum order at {} {}.".format(
            offer["supplier"], offer["moq_units"], offer["unit"]
        )
    elif any(word in normalized for word in ("best", "recommend", "which one", "should")):
        offer = best
        answer = "{} is the best overall balance: {} landed, a {}, and a {} rating. {}".format(
            offer["supplier"],
            _money(offer["landed_cost"]),
            _lead_phrase(offer["lead_time_days"]),
            offer["rating"],
            "Documentation is verified." if offer["verified"] else "Documentation still needs checking.",
        )
    elif any(word in normalized for word in ("compare", "summary", "tell me", "overview")):
        answer = payload.get("summary", "I have a comparison ready.")
    else:
        offer = best
        answer = "{} is currently the strongest option at {} landed. Ask me about the cheapest, fastest, or lowest minimum order for a specific comparison.".format(
            offer["supplier"], _money(offer["landed_cost"])
        )
    links = [
        {
            "url": offer["source_url"],
            "title": offer["source_title"],
            "supplier": offer["supplier"],
            "image_url": offer["image_url"],
        }
        for offer in (cheapest, fastest, best)
    ]
    unique = {link["url"]: link for link in links}
    if payload.get("index", {}).get("is_demo"):
        answer = "Illustrative demonstration data only, not a current quote or supplier verification. " + answer
    return {"answer": answer, "links": list(unique.values()), "task_id": payload.get("task_id")}


def quote_draft(payload, offer, profile=None):
    profile = profile or {}
    quantity = payload.get("quantity", {}).get("quantity_label", "the requested quantity")
    ship_to = profile.get("ship_to") or "the delivery address on file"
    requested = payload.get("requested_units", offer.get("order_units", 0))
    lines = [
        "Subject: Quote request — {} of {}".format(quantity, payload.get("product", {}).get("name", "product").lower()),
        "",
        "Hello {},".format(offer["supplier"]),
        "",
        "We are sourcing {} of {} for delivery to {}.".format(
            quantity, payload.get("product", {}).get("name", "product").lower(), ship_to
        ),
        "Please confirm the following before we proceed:",
        "- Unit price for {} and the applicable pack or carton pricing".format(
            payload.get("product", {}).get("name", "the product").lower()
        ),
        "- Minimum order quantity and lead time",
        "- Shipping cost and estimated delivery date",
        "- Quote validity period and any payment terms",
        "- Certifications and batch documentation",
        "",
        "For reference, your current listing shows {} per {} with a {} minimum and a {}.".format(
            _money(offer["unit_price"]), offer["unit"], offer["moq_label"], _lead_phrase(offer["lead_time_days"])
        ),
        "",
        "Thank you,",
        profile.get("buyer_name") or "Procurement team",
        profile.get("company") or "",
    ]
    draft = "\n".join(line for line in lines if line is not None)
    return {
        "kind": "quote_request",
        "supplier": offer["supplier"],
        "offer_id": offer["id"],
        "task_id": payload.get("task_id"),
        "draft": draft,
        "requested_units": requested,
    }


def purchase_order_draft(payload, offer, quantity, profile=None):
    profile = profile or {}
    quantity = max(1, int(quantity or payload.get("requested_units", 1)))
    moq = int(offer.get("moq_units", 1) or 1)
    if quantity < moq:
        quantity = moq
    subtotal = round(float(offer["unit_price"]) * quantity, 2)
    shipping = 0.0 if offer.get("free_shipping") else float(offer.get("shipping", 0) or 0)
    total = round(subtotal + shipping, 2)
    threshold = float(profile.get("approval_threshold") or 0)
    lines = [
        "PURCHASE ORDER — DRAFT FOR HUMAN APPROVAL",
        "",
        "Supplier: {}".format(offer["supplier"]),
        "Product: {}".format(payload.get("product", {}).get("name", "")),
        "Quantity: {} {}".format(quantity, plural_unit(offer["unit"], quantity)),
        "Unit price: {} per {}".format(_money(offer["unit_price"]), offer["unit"]),
        "Subtotal: {}".format(_money(subtotal)),
        "Shipping: {}".format("Included" if shipping == 0 else _money(shipping)),
        "Estimated total: {}".format(_money(total)),
        "Ship to: {}".format(profile.get("ship_to") or "Not configured"),
        "Payment method: {}".format(
            (profile.get("payment_method") or "approval_only").replace("_", " ").capitalize()
        ),
        "",
        "No order has been placed. This draft requires human approval and supplier confirmation.",
    ]
    if threshold and total > threshold:
        lines.append("This total exceeds the configured approval threshold of {}.".format(_money(threshold)))
    return {
        "kind": "purchase_order",
        "supplier": offer["supplier"],
        "offer_id": offer["id"],
        "task_id": payload.get("task_id"),
        "quantity": quantity,
        "subtotal": subtotal,
        "shipping": shipping,
        "amount": total,
        "currency": "USD",
        "draft": "\n".join(lines),
        "approval_threshold": threshold,
    }
