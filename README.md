# E-C PlasticKG: An Evidence-Centric and Scope-Aware Knowledge Graph Framework for Plastic Waste Management

Dynamic, keyword-driven, evidence-centric and scope-aware Knowledge Graph generation for
plastic waste management research abstracts.

Search a keyword (e.g. *Pyrolysis*, *PET*, *Microplastics*) and the system builds a **separate**
claim-based graph for that topic instead of one global graph.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                                          # open http://127.0.0.1:5000
pytest                                                 # run tests
python -m plastickg.cli "Pyrolysis" --out pyrolysis.json   # headless export
```
The UI loads vis-network and fonts from CDNs, so it needs internet access in the browser.

## Pipeline
```
keyword -> synonym expansion -> retrieval (TF-IDF) -> relevant abstracts
        -> sentence-level claim extraction (entities, scope, polarity, uncertainty)
        -> claim-to-claim relations -> keyword-specific graph (JSON) -> interactive view
```

| Module | Role |
|---|---|
| `plastickg/retrieval.py` | Keyword to abstracts; TF-IDF backend, optional sentence-transformers backend |
| `plastickg/extraction.py` | Claims, entities, subject/object, scope, polarity, uncertainty, evidence offsets |
| `plastickg/graph_builder.py` | Nodes, labelled edges, claim relations (Supports / Challenges / Refines / Inconclusive) |
| `plastickg/lexicon.py` | All domain vocabulary and cue words (edit here to extend) |
| `app.py` + `templates/` + `static/` | Flask API and the search / graph UI |

## Graph schema
- **Nodes:** Entity, Claim, Evidence (verbatim passage + character offsets), Uncertainty (U1/U2/U3)
- **Edges:** `Subject`, `Has Object` (Claim to Entity); `Evidence` (Claim to Evidence);
  `From Finding` (Uncertainty to Claim); `Supports`, `Challenges`, `Refines`, `Inconclusive` (Claim to Claim)
- **Scope** is stored on each Claim: polymer, temperature, reaction time, catalyst, medium.
  Values not stated in the claim sentence but found elsewhere in the abstract are flagged `inherited_from_abstract`.

### Uncertainty levels
| Level | Meaning | Triggered by |
|---|---|---|
| U1 | Low | Direct or quantified result |
| U2 | Moderate | Hedges: may, might, could, suggests, potential |
| U3 | High | Inconclusive, unclear, needs further study |

### Claim relation rules (same subject and same object, different abstracts)
1. Either claim U3 -> `Inconclusive`
2. Opposite polarity -> `Challenges`
3. Same polarity but different scope values -> `Refines`
4. Otherwise -> `Supports`

## Important notes
- `data/abstracts.json` contains **10 illustrative, author-written placeholder abstracts**, not real
  publications. Replace them with real abstracts (same JSON format: `id`, `title`, `text`).
- Extraction is rule-based so it is transparent and runs offline. It is a baseline: expect misses on
  complex sentences. To go further, swap `extract_claims` for an LLM or NLI-based extractor that returns
  the same `Claim` objects, and enable semantic retrieval:
  `pip install sentence-transformers`, then `PlasticKG(backend="semantic")`.
- Retrieval quality and relation logic (which pairs count as comparable) are the main places to improve.

## Layout
```
EC_PlasticKG/
  app.py  requirements.txt  README.md
  data/        abstracts.json  keywords.json
  plastickg/   retrieval.py extraction.py graph_builder.py lexicon.py pipeline.py cli.py
  templates/   index.html
  static/      app.js style.css
  tests/       test_pipeline.py
  docs/        architecture.md
```

## Research Contributions and Design Principles

E-C PlasticKG follows these key design principles:

- **Topic-specific graph generation:** Creates a separate knowledge graph for each search keyword.
- **Evidence traceability:** Connects extracted claims to supporting text passages.
- **Scope awareness:** Stores experimental conditions such as polymer type, temperature, reaction time, catalyst, and medium.
- **Uncertainty representation:** Uses U1, U2, and U3 to represent different uncertainty levels.
- **Explicit claim relationships:** Represents Supports, Challenges, Refines, and Inconclusive relationships.

These principles aim to make knowledge graph exploration more transparent, interpretable, and context-aware.
