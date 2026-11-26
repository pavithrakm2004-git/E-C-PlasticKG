"""Generate E-C PlasticKG predictions and evaluate them against an annotation workbook.

This script uses the project's existing rule-based extractor. It deliberately uses
exact matching for entities/claim sentences; semantic claim matching still needs
human adjudication. Evidence semantic support is NOT inferred from text alignment.

Commands (run from the project root):
  python evaluation.py predict --gold data/EC_PlasticKG_GOLD_VERIFIED.xlsx
  python evaluation.py evaluate --gold data/EC_PlasticKG_GOLD_VERIFIED.xlsx \
      --predictions results/predictions_30.json --out results/evaluation_matrix.xlsx

For a clearly labelled preliminary run on an unverified draft only:
  add --allow-unverified to the evaluate command.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from plastickg.extraction import extract_claims, split_sentences, find_entities  # noqa: E402
from plastickg import lexicon as L  # noqa: E402

DEFAULT_DATA = ROOT / "data" / "openalex_abstracts.json"
DEFAULT_GOLD = ROOT / "data" / "EC_PlasticKG_GOLD_VERIFIED.xlsx"
DEFAULT_PRED = ROOT / "results" / "predictions_30.json"
DEFAULT_REPORT = ROOT / "results" / "evaluation_matrix.xlsx"


def resolve_gold_workbook(requested):
    requested = Path(requested).resolve()
    if requested.is_file():
        return requested
    data_dir = ROOT / "data"
    candidates = sorted(
        (p for p in data_dir.glob("*.xlsx")
         if "EC_PlasticKG" in p.name and ("GOLD" in p.name.upper() or "ANNOTATION" in p.name.upper())),
        key=lambda p: p.name.casefold(),
    )
    if candidates:
        return candidates[0]
    return requested


def norm(value):
    if value is None:
        return ""
    value = str(value).strip().casefold()
    value = re.sub(r"\s+", " ", value)
    return value


def cell(row, name):
    return row.get(name) if isinstance(row, dict) else None


def read_sheet(path, sheet):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Required workbook not found: {path}\n"
            "Place EC_PlasticKG_GOLD_VERIFIED.xlsx in the data folder or pass --gold."
        )
    wb = load_workbook(path, data_only=True)
    ws = wb[sheet]
    headers = [c.value for c in ws[1]]
    return [dict(zip(headers, values)) for values in ws.iter_rows(min_row=2, values_only=True)
            if any(v is not None for v in values)]


def read_abstracts_from_workbook(path):
    rows = read_sheet(path, "Abstracts")
    out = {}
    for r in rows:
        aid = str(r["Abstract ID"]).strip()
        out[aid] = {
            "id": aid,
            "title": r.get("Title") or "",
            "text": r.get("Original abstract text") or "",
        }
    if len(out) != 30:
        raise ValueError(f"Expected 30 unique abstracts in the workbook; found {len(out)}.")
    return out


def entity_mentions(abstract):
    """Run the project's entity recognizer over every sentence in an abstract."""
    text = abstract["text"]
    found = []
    for sentence, sent_start, _sent_end in split_sentences(text):
        for ent in find_entities(sentence):
            # Recover the actual matched surface span for a correct end offset.
            pattern = next((rx for name, _typ, rx in L.ENTITY_REGEX if name == ent["name"]), None)
            match = None
            if pattern is not None:
                match = next((m for m in pattern.finditer(sentence)
                              if m.start() == ent["pos"]), None)
            if match is None:
                continue
            s, e = sent_start + match.start(), sent_start + match.end()
            found.append({
                "abstract_id": abstract["id"],
                "text": text[s:e],
                "normalized": ent["name"].casefold(),
                "type": ent["type"],
                "start": s,
                "end": e,
            })
    return found


def command_predict(args):
    gold_path = resolve_gold_workbook(args.gold)
    source = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    source_by_id = {str(a["id"]): a for a in source}

    if gold_path.is_file():
        abstracts = read_abstracts_from_workbook(gold_path)
        gold_reference = str(gold_path)
        dataset_limit_note = "workbook IDs and source text"
    else:
        if len(source) < 30:
            raise ValueError(f"Expected at least 30 records in the dataset; found {len(source)}.")
        source_30 = source[:30]
        abstracts = {
            str(a["id"]): {
                "id": str(a["id"]),
                "title": a.get("title", ""),
                "text": a.get("text", ""),
            }
            for a in source_30
        }
        gold_reference = "not provided; used first 30 dataset records"
        dataset_limit_note = "first 30 dataset records"
        print(f"Gold workbook not found; using {dataset_limit_note}.")

    missing = sorted(set(abstracts) - set(source_by_id))
    if missing:
        raise ValueError(f"These workbook IDs are missing from OpenAlex dataset: {missing}")

    predictions = {"metadata": {
        "project": "EC_PlasticKG_FINAL",
        "method": "existing rule-based extraction pipeline",
        "dataset": str(Path(args.dataset)),
        "gold_workbook_used_only_for_sample_IDs_and_source_text": gold_reference,
        "matching_note": "Predictions are separate from gold annotations.",
        "abstract_count": len(abstracts),
    }, "abstracts": []}

    for aid, workbook_abstract in abstracts.items():
        source_abstract = source_by_id[aid]
        if norm(workbook_abstract["text"]) != norm(source_abstract.get("text", "")):
            raise ValueError(f"Abstract text mismatch for {aid}. Stop: do not evaluate mismatched text.")
        # Use source dataset content, not annotation columns, for prediction input.
        a = {"id": aid, "title": source_abstract.get("title", ""),
             "text": source_abstract["text"]}
        claims = [c.to_dict() for c in extract_claims(a)]
        entities = entity_mentions(a)
        predictions["abstracts"].append({
            "id": aid,
            "title": a["title"],
            "entities": entities,
            "claims": claims,
        })

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8")
    total_claims = sum(len(a["claims"]) for a in predictions["abstracts"])
    total_entities = sum(len(a["entities"]) for a in predictions["abstracts"])
    print(f"Saved predictions: {out}")
    print(f"Abstracts: {len(abstracts)} | predicted entity mentions: {total_entities} | predicted claims: {total_claims}")


def counts_to_metrics(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def exact_set_counts(gold_items, pred_items):
    g, p = Counter(gold_items), Counter(pred_items)
    tp = sum((g & p).values())
    fp = sum((p - g).values())
    fn = sum((g - p).values())
    return tp, fp, fn


def confusion_rows(pairs, labels):
    matrix = {actual: {pred: 0 for pred in labels} for actual in labels}
    for actual, pred in pairs:
        if actual in matrix and pred in matrix[actual]:
            matrix[actual][pred] += 1
    return matrix


def write_table(ws, headers, rows):
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="244062")
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        max_len = max((len(str(c.value)) if c.value is not None else 0) for c in col[:100])
        ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 48)


def command_evaluate(args):
    gold_path = resolve_gold_workbook(args.gold)
    pred_path = Path(args.predictions).resolve()
    predictions = json.loads(pred_path.read_text(encoding="utf-8"))
    pred_by_id = {a["id"]: a for a in predictions["abstracts"]}

    # Check whether this is actually a reviewed/adjudicated workbook.
    sheets_to_check = ["Gold_Entities", "Gold_Claims", "Gold_Evidence",
                       "Gold_Scope", "Gold_Uncertainty", "Gold_Relations"]
    draft_markers = []
    for sheet in sheets_to_check:
        for row in read_sheet(gold_path, sheet):
            annotator = norm(row.get("Annotator ID"))
            if "ai-draft" in annotator or "human review required" in norm(row.get("Notes")):
                draft_markers.append(sheet)
                break
    review_rows = read_sheet(gold_path, "Annotation_Review")
    pending = [r for r in review_rows if norm(r.get("Adjudicated label")) in
               ("", "not adjudicated", "pending", "not yet reviewed")]
    verified = not draft_markers and not pending
    if not verified and not args.allow_unverified:
        raise SystemExit(
            "STOP: This workbook still appears unverified (AI-DRAFT labels or pending adjudication).\n"
            "Finish human review/adjudication first. For a clearly labelled preliminary diagnostic only, "
            "rerun with --allow-unverified."
        )

    gold_entities = read_sheet(gold_path, "Gold_Entities")
    gold_claims = read_sheet(gold_path, "Gold_Claims")
    gold_scope = read_sheet(gold_path, "Gold_Scope")
    gold_unc = read_sheet(gold_path, "Gold_Uncertainty")
    gold_evidence = read_sheet(gold_path, "Gold_Evidence")
    gold_rel = read_sheet(gold_path, "Gold_Relations")

    # Entity extraction: exact canonicalized entity text + entity type + abstract ID.
    g_entities = [(str(r["Abstract ID"]), norm(r.get("Normalized entity") or r.get("Entity text (exact)")),
                   norm(r.get("Entity type"))) for r in gold_entities if r.get("Entity text (exact)")]
    p_entities = [(a["id"], norm(e.get("normalized") or e.get("text")), norm(e.get("type")))
                  for a in predictions["abstracts"] for e in a.get("entities", [])]
    ent_tp, ent_fp, ent_fn = exact_set_counts(g_entities, p_entities)

    # Claims: strict normalized sentence equality. Paraphrase/semantic equivalence is not guessed.
    g_claim_key = {}
    for r in gold_claims:
        if r.get("Claim sentence / text"):
            g_claim_key[(str(r["Abstract ID"]), norm(r["Claim sentence / text"]))] = r
    p_claim_key = {}
    for a in predictions["abstracts"]:
        for c in a.get("claims", []):
            p_claim_key[(a["id"], norm(c.get("text")))] = c
    g_claims = list(g_claim_key.keys())
    p_claims = list(p_claim_key.keys())
    cl_tp, cl_fp, cl_fn = exact_set_counts(g_claims, p_claims)
    matched_claim_keys = set(g_claim_key) & set(p_claim_key)
    gold_claim_by_id = {str(r["Gold claim ID"]): r for r in gold_claims if r.get("Gold claim ID")}

    # Uncertainty confusion matrix on exact-matched claims only.
    unc_by_claim = {str(r["Gold claim ID"]): r for r in gold_unc if r.get("Gold claim ID")}
    unc_pairs = []
    for key in matched_claim_keys:
        gr = g_claim_key[key]
        ur = unc_by_claim.get(str(gr.get("Gold claim ID")))
        if not ur:
            continue
        actual = str(ur.get("Gold label (U1/U2/U3/Unclear)") or "Unclear").strip()
        pred = str(p_claim_key[key].get("uncertainty") or "Unclear").strip()
        if actual in ("U1", "U2", "U3") and pred in ("U1", "U2", "U3"):
            unc_pairs.append((actual, pred))
    unc_labels = ["U1", "U2", "U3"]
    unc_matrix = confusion_rows(unc_pairs, unc_labels)

    # Scope: compare each reviewed scope field for matched claims. Unclear is excluded.
    scope_details = []
    scope_correct = scope_total = 0
    scope_by_claim = defaultdict(list)
    for r in gold_scope:
        scope_by_claim[str(r.get("Gold claim ID"))].append(r)
    for key in matched_claim_keys:
        gr = g_claim_key[key]
        claim_id = str(gr.get("Gold claim ID"))
        pred_scope = p_claim_key[key].get("scope") or {}
        for sr in scope_by_claim.get(claim_id, []):
            field = str(sr.get("Scope field") or "")
            basis = norm(sr.get("Source basis (Explicit/Elsewhere/Absent/Unclear)"))
            if basis == "unclear" or not field:
                continue
            expected = sr.get("Normalized value") or sr.get("Value as stated")
            got = pred_scope.get(field)
            if basis == "absent":
                correct = not bool(got)
            else:
                correct = norm(expected) == norm(got)
            scope_total += 1
            scope_correct += int(correct)
            scope_details.append((key[0], claim_id, field, expected, got, basis, correct))

    # Evidence: validate offsets/text alignment only. This is NOT semantic support accuracy.
    abstracts = read_abstracts_from_workbook(gold_path)
    evidence_details = []
    for er in gold_evidence:
        aid = str(er.get("Abstract ID"))
        text = abstracts.get(aid, {}).get("text", "")
        start, end = er.get("Start offset"), er.get("End offset")
        passage = er.get("Evidence passage (exact)") or ""
        valid = isinstance(start, int) and isinstance(end, int) and text[start:end] == passage
        evidence_details.append((aid, er.get("Gold claim ID"), start, end, passage, valid,
                                 er.get("Semantic support (Yes/No/Unclear)")))

    # Relations: only the claim pairs explicitly listed in the workbook are scored.
    # The system's rule-based relation is reconstructed using the same subject/object rule.
    relation_labels = ["Supports", "Challenges", "Refines", "Inconclusive", "None"]
    rel_pairs = []
    rel_details = []
    for rr in gold_rel:
        id1, id2 = str(rr.get("Claim 1 ID")), str(rr.get("Claim 2 ID"))
        c1g, c2g = gold_claim_by_id.get(id1), gold_claim_by_id.get(id2)
        if not c1g or not c2g:
            continue
        k1 = (str(c1g["Abstract ID"]), norm(c1g.get("Claim sentence / text")))
        k2 = (str(c2g["Abstract ID"]), norm(c2g.get("Claim sentence / text")))
        c1p, c2p = p_claim_key.get(k1), p_claim_key.get(k2)
        if not c1p or not c2p:
            pred_relation = "None"
            reason = "One or both claims were not extracted/matched."
        elif k1[0] == k2[0]:
            pred_relation, reason = "None", "Relation pairs must be cross-abstract."
        elif not c1p.get("subject") or not c2p.get("subject") or not c1p.get("object") or not c2p.get("object"):
            pred_relation, reason = "None", "A predicted claim endpoint is missing."
        elif (c1p["subject"].get("name") != c2p["subject"].get("name") or
              c1p["object"].get("name") != c2p["object"].get("name")):
            pred_relation, reason = "None", "System relation rule requires identical subject and object."
        elif "U3" in (c1p.get("uncertainty"), c2p.get("uncertainty")):
            pred_relation, reason = "Inconclusive", "At least one predicted claim is U3."
        elif (c1p.get("polarity") != c2p.get("polarity") and
              "neutral" not in (norm(c1p.get("polarity")), norm(c2p.get("polarity")))):
            pred_relation, reason = "Challenges", "Predicted polarities differ."
        elif any((c1p.get("scope") or {}).get(f) != (c2p.get("scope") or {}).get(f)
                 for f in ("temperature", "reaction_time", "catalyst", "polymer")
                 if f in (c1p.get("scope") or {}) and f in (c2p.get("scope") or {})):
            pred_relation, reason = "Refines", "A shared scope field differs."
        else:
            pred_relation, reason = "Supports", "Same predicted subject/object; no conflict rule fired."
        actual = str(rr.get("Gold relation (Supports/Challenges/Refines/Inconclusive/None)") or "").strip()
        if actual in relation_labels:
            rel_pairs.append((actual, pred_relation))
        rel_details.append((id1, id2, actual, pred_relation, reason))
    rel_matrix = confusion_rows(rel_pairs, relation_labels)

    # Build output workbook.
    wb = Workbook()
    ws = wb.active
    ws.title = "Evaluation_Summary"
    status = "VERIFIED" if verified else "PRELIMINARY - UNVERIFIED DRAFT"
    summary = [
        ("Evaluation status", status),
        ("Prediction method", "Existing EC_PlasticKG rule-based extractor"),
        ("Abstracts in prediction file", len(predictions["abstracts"])),
        ("Entity TP", ent_tp), ("Entity FP", ent_fp), ("Entity FN", ent_fn),
        ("Entity Precision", counts_to_metrics(ent_tp, ent_fp, ent_fn)[0]),
        ("Entity Recall", counts_to_metrics(ent_tp, ent_fp, ent_fn)[1]),
        ("Entity F1", counts_to_metrics(ent_tp, ent_fp, ent_fn)[2]),
        ("Claim TP (strict sentence match)", cl_tp), ("Claim FP", cl_fp), ("Claim FN", cl_fn),
        ("Claim Precision", counts_to_metrics(cl_tp, cl_fp, cl_fn)[0]),
        ("Claim Recall", counts_to_metrics(cl_tp, cl_fp, cl_fn)[1]),
        ("Claim F1", counts_to_metrics(cl_tp, cl_fp, cl_fn)[2]),
        ("Matched claims used for uncertainty", len(unc_pairs)),
        ("Uncertainty accuracy", sum(1 for a, p in unc_pairs if a == p) / len(unc_pairs) if unc_pairs else 0),
        ("Scope field comparisons", scope_total),
        ("Scope exact-match accuracy", scope_correct / scope_total if scope_total else 0),
        ("Evidence offsets valid", sum(1 for r in evidence_details if r[5])),
        ("Evidence offsets checked", len(evidence_details)),
        ("Evidence semantic support", "Not automatically evaluated; requires human review"),
        ("Relation pairs evaluated", len(rel_pairs)),
        ("Relation accuracy on listed pairs", sum(1 for a, p in rel_pairs if a == p) / len(rel_pairs) if rel_pairs else 0),
        ("Claim matching limitation", "Strict normalized sentence equality; paraphrases are not matched automatically."),
        ("Relation limitation", "Only relation pairs listed in Gold_Relations are evaluated; pair coverage may be incomplete."),
    ]
    write_table(ws, ["Measure", "Value"], summary)

    # Per-class metrics for uncertainty and relation.
    def add_confusion(sheet_name, labels, matrix, pairs):
        w = wb.create_sheet(sheet_name)
        rows = [("Actual \\ Predicted", *labels)]
        for lab in labels:
            rows.append((lab, *[matrix[lab][pred] for pred in labels]))
        write_table(w, rows[0], rows[1:])
        detail_rows = []
        for lab in labels:
            tp = matrix[lab][lab]
            fp = sum(matrix[a][lab] for a in labels if a != lab)
            fn = sum(matrix[lab][p] for p in labels if p != lab)
            p, r, f = counts_to_metrics(tp, fp, fn)
            detail_rows.append((lab, tp, fp, fn, p, r, f))
        start = w.max_row + 3
        w.cell(start, 1, "Per-class metrics")
        for j, h in enumerate(["Class", "TP", "FP", "FN", "Precision", "Recall", "F1"], 1):
            w.cell(start + 1, j, h)
        for i, row in enumerate(detail_rows, start + 2):
            for j, value in enumerate(row, 1):
                w.cell(i, j, value)
    add_confusion("Confusion_Uncertainty", unc_labels, unc_matrix, unc_pairs)
    add_confusion("Confusion_Relations", relation_labels, rel_matrix, rel_pairs)

    write_table(wb.create_sheet("Scope_Details"),
                ["Abstract ID", "Gold claim ID", "Field", "Gold value", "Predicted value", "Gold source basis", "Exact match"],
                scope_details)
    write_table(wb.create_sheet("Evidence_Alignment"),
                ["Abstract ID", "Gold claim ID", "Start", "End", "Evidence passage", "Offset text matches", "Human semantic label"],
                evidence_details)
    write_table(wb.create_sheet("Relation_Details"),
                ["Gold Claim 1", "Gold Claim 2", "Gold relation", "Predicted relation", "Reason"],
                rel_details)

    # Detailed extraction comparison tables.
    entity_detail = [(a, n, t, "Gold") for a, n, t in g_entities]
    entity_detail += [(a, n, t, "Predicted") for a, n, t in p_entities]
    write_table(wb.create_sheet("Entity_Items"),
                ["Abstract ID", "Normalized entity", "Entity type", "Source"], entity_detail)
    claim_detail = []
    for key in sorted(set(g_claim_key) | set(p_claim_key)):
        claim_detail.append((key[0], g_claim_key.get(key, {}).get("Gold claim ID", ""),
                             g_claim_key.get(key, {}).get("Claim sentence / text", ""),
                             p_claim_key.get(key, {}).get("id", ""),
                             p_claim_key.get(key, {}).get("text", ""),
                             "MATCH" if key in matched_claim_keys else
                             ("GOLD ONLY / FN" if key in g_claim_key else "PREDICTION ONLY / FP")))
    write_table(wb.create_sheet("Claim_Items"),
                ["Abstract ID", "Gold claim ID", "Gold claim text", "Predicted claim ID", "Predicted claim text", "Match status"],
                claim_detail)

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Saved evaluation workbook: {out}")
    print(f"Status: {status}")
    print(f"Entity P/R/F1: {counts_to_metrics(ent_tp, ent_fp, ent_fn)}")
    print(f"Claim P/R/F1: {counts_to_metrics(cl_tp, cl_fp, cl_fn)}")
    print("Note: inspect the report limitations before using any values in a paper.")


def main():
    parser = argparse.ArgumentParser(description="E-C PlasticKG prediction and evaluation")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("predict", help="Generate predictions for the 30 workbook abstracts")
    p.add_argument("--gold", default=str(DEFAULT_GOLD), help="Workbook used to get the 30 abstract IDs")
    p.add_argument("--dataset", default=str(DEFAULT_DATA), help="100-record OpenAlex JSON dataset")
    p.add_argument("--out", default=str(DEFAULT_PRED), help="Output prediction JSON")
    p.set_defaults(func=command_predict)

    e = sub.add_parser("evaluate", help="Compare predictions against the annotation workbook")
    e.add_argument("--gold", default=str(DEFAULT_GOLD), help="Human-reviewed annotation workbook")
    e.add_argument("--predictions", default=str(DEFAULT_PRED), help="Prediction JSON from predict command")
    e.add_argument("--out", default=str(DEFAULT_REPORT), help="Output evaluation Excel workbook")
    e.add_argument("--allow-unverified", action="store_true",
                   help="Allow a preliminary diagnostic on unverified labels; report will be marked unverified")
    e.set_defaults(func=command_evaluate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
