# Experiments

## 1. Recall against a published paper's reference list (2026-10-10)

**Question:** Of the references in a real paper on the topic, how many does LR-AI find, and how does it rate them?

### Setup

- **Review topic:** "The systematic literature review as a research genre before 2012"
- **Run:** `/lr-ai:lit-review` in automatic mode, LR-AI 0.2.7, run folder `lr-runs/slr-genre-2026-10-10`. The run folder is not committed.
- **Benchmark paper:** Ramey & Rao (2011), *The systematic literature review as a research genre*, IEEE ProComm,
  [doi:10.1109/IPCC.2011.6087229](https://ieeexplore.ieee.org/document/6087229/). It has 15 references (taken from Crossref).
- **Run settings:**
  - Years up to 2011.
  - 6 seed queries plus 32 known papers I supplied. Four of the benchmark's references were among those known papers.
  - 4 boolean queries. Semantic Scholar was rate-limited, so only OpenAlex and arXiv answered.
  - Screening first, then one snowball round from the included papers (30 references and 10 citing papers per paper).
  - Filters: `require_any` = review*/synthes*/meta-analy*/evidence, and `min_hits: 2`.
- **Run totals:**
  - 4,440 records found, 4,098 unique.
  - 3,305 removed by automatic filters.
  - 793 screened.
  - 429 included: 282 core, 147 skim.

The benchmark paper itself was found by the OpenAlex keyword search and rated **core / high**
(category: Origins & Spread of the Genre (RQ1)).

### Results

| | Count | Share of 15 |
|---|---|---|
| Found by LR-AI | 14 | 93% |
| Included in the final review | 5 | 33% |
| Removed by automatic filters | 9 | 60% |
| Not found | 1 (MeSH, a website) | 7% |
| Removed by the AI screeners | 0 | 0% |

**Priority of the included references:** all 5 are core, rated 3 high, 2 medium and 0 low.

| Ref | Paper | Status / priority | Category | How it was found |
|---|---|---|---|---|
| 1 | Mulrow 1994, *Rationale for systematic reviews* | core / high | Origins & Spread (RQ1) | known paper + backward (11 links) |
| 3 | Crowther & Cook 2008, *How to use an SLR and meta-analysis* | core / medium | Methods & Guidance (RQ2) | backward only (2 links, one of them the benchmark) |
| 4 | Tranfield et al. 2003, evidence-informed management | core / high | Origins & Spread (RQ1) | known paper + backward + forward (9 links) |
| 5 | Brereton et al. 2006/07, SLRs in software engineering | core / high | Origins & Spread (RQ1) | known paper + backward (5 links) |
| 6 | Petticrew 2001, *Astronomy to zoology* | core / medium | Origins & Spread (RQ1) | known paper + backward + forward (10 links) |

**Which step found them:**

- Refs 1, 4, 5 and 6 came from the known-paper list. Snowballing also linked each of them from 5 to 11 other papers.
- The other 10 references were found only by backward snowballing:
  - 8 only through the benchmark's own reference list
  - ref 3 through the benchmark and one other included paper
  - ref 2 through one other paper
- No reference was found by the keyword searches.

**Why the 9 were removed:**

- 6 contain none of the required keywords: refs 8, 9, 10, 12, 13, 14.
- 3 were linked from only one included paper (`min_hits: 2`): refs 2, 7, 11.

**The references fall into two groups:**

- **8 are about the review method itself** (refs 1–7 and 15). LR-AI found 7 of them and included 5 (63%).
  - It missed the Cochrane Collaboration (ref 2) and an applied review on workflow research (ref 7). Both were removed by `min_hits`.
  - Ref 7 would be excluded under the criteria anyway, because it only applies the review method.
- **7 are examples from the benchmark's own field**: technical communication (refs 8–10) and ICT for development (refs 11–14).
  All 7 were filtered out, which is correct for this review's research questions.

**Other numbers:**

- **Citations:** the included references have a median of about 1,700 citations. The removed ones have a median of about 50.
- **Coverage:** the 5 included references are 1.2% of the 429 included papers. The LR-AI review covers the topic much more widely.

### Takeaways

- LR-AI found almost every reference (14 of 15), and its screeners did not wrongly exclude any.
- Every loss came from the automatic filters, mostly on purpose (off-topic example papers). `min_hits: 2` also removed two
  on-topic method references, ref 2 (Cochrane) and ref 7, the cost of keeping screening manageable.
- The four classic method papers came from the known-paper list. This test cannot show whether keyword search alone would have found them.
- Limitation: one benchmark paper, with a short and mixed reference list.
