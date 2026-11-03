"""Approach names for reading: "Street [bound]", with the link ID where the name alone is not enough."""
from __future__ import annotations


def approach_label(row: dict) -> str:
    """The label fixed at screening time (unique within the site) when there is one; otherwise "Street [bound]".
    Without a bound the link ID is kept so two links of one street stay distinct; without a reliable street name
    (Neo4j or the validated road-link mapping) the link ID is the name."""
    if row.get("label"):
        return row["label"]
    street, bound = row.get("street"), row.get("bound")
    if street and bound:
        return f"{street} [{bound}]"
    if street:
        return f"{street} (link {row['link']})"
    return f"Link {row['link']} [{bound}] (no street name)" if bound else f"Link {row['link']} (no street name)"


def label_site(*groups: list[dict]) -> None:
    """Give every approach row of one site a label, in place. Two links that would read the same (e.g. two
    "William Street [N]" links) get their link ID added, so every label names one link."""
    rows = [r for g in groups for r in g if r.get("link")]
    info = {}
    for r in rows:
        i = info.setdefault(r["link"], {"link": r["link"], "street": None, "bound": None})
        i["street"] = i["street"] or r.get("street")
        i["bound"] = i["bound"] or r.get("bound")
    base = {link: approach_label(i) for link, i in info.items()}
    seen = {}
    for link, text in base.items():
        seen.setdefault(text, []).append(link)
    for r in rows:
        text = base[r["link"]]
        if len(seen[text]) > 1 and "(link " not in text:
            text = f"{text} (link {r['link']})"
        r["label"] = text
