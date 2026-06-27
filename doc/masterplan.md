# Bulk AI Product Description SaaS — Serbia GTM & Build Plan

> **One-line verdict:** The generic version of this idea is dead on arrival. "AI writes
> descriptions" is a free Shopify feature and Describely already does catalog-scale bulk
> generation with enrichment + store sync at $0.75/product. You cannot out-feature them.
> But there *is* a narrow, defensible wedge in Serbia — and it's not the part most founders
> would get excited about.

---

## 1. Research summary — the competitive reality

**The global field is crowded and converging on the same feature set.**

- **Describely** — scale leader. Generate 10–10,000 descriptions at once; sync with Shopify,
  Wix, WooCommerce, Akeneo; enrich missing data from just a SKU or title. ~15 languages as a
  parameter. Fast deploy (~3-day setup). Pricing: **$0.75/product, $0.55/enrichment credit,
  $0.05/image** (pay-as-you-go).
- **Hypotenuse AI** — enterprise play. Thousands of SKUs in minutes, scales to millions of
  products; enriches from web, URL, image, barcode; runs **marketplace content audits**
  (Amazon, Google Shopping compliance). Quote-only pricing.
- **Jasper / Copy.ai / Writesonic** — marketing-copy generalists, multilingual (Jasper ~27,
  Rytr 35+), but no catalog ops.
- **Shopify Magic / ChatGPT** — the free floor. One product at a time, no brand governance.

**Three things the leaders treat as settled — relevant to the wedge:**

1. **Output quality is bounded by input data, not the model.** Every serious player now leads
   with *enrichment*, not generation. Missing attributes → vague output regardless of tool.
   This is the real battleground.
2. **They optimize for English SEO + "GEO" (AI-search readiness).** Non-English = a model
   parameter ("output language: Serbian"). No deterministic handling of Slavic case/gender.
3. **They sell to Shopify/BigCommerce mid-market.** Integrations, case studies, and motion all
   assume that stack.

**Serbian market reality (the opening):**

- Market size: Statista B2C ~**US$1.13bn (2025)**; broader estimates $3.4–3.6bn incl. B2B.
  Growth is real but **~6.9–7.1% CAGR**, *not* 28%. (The 22.3% figure is from a low-quality
  report with "USD XXX" placeholders — do not quote it to investors.) Cart abandonment ~76%.
- Big catalog players, concentrated: **Shoppster, Gigatron, Tehnomanija, Sport Vision,
  Fashion Company, Forma Ideale, Idea, Emmezeta.** Consumer electronics = largest category
  (~27.4% share); fashion growing ~8.5% CAGR. Electronics + fashion = huge SKU counts +
  thin, duplicated, manufacturer-fed copy.
- **Legal hook = strongest non-language moat.** 2021 Consumer Protection Law (*Zakon o zaštiti
  potrošača*, 88/2021, EU-harmonized): Right to Information (clear, accurate, complete);
  distance-contract info must be **in Serbian**, with **burden of proof on the trader**.
  Hallucinated specs aren't just bad copy — they're compliance + false-advertising exposure,
  and they feed the COD-driven returns problem.

---

## 2. The wedge — and the ideas killed first

**KILLED — "Best AI descriptions in Serbian."** Unverifiable, undefensible; Describely adds a
better Serbian model the week you launch. Prose quality is not a moat.

**KILLED — self-serve SaaS for SMBs.** The 10–500 SKU merchant uses ChatGPT for free. No money,
murderous support load.

**THE WEDGE — three layers, ordered by defensibility:**

> **You are not a description generator. You are a Serbian-language catalog correctness and
> compliance engine that happens to generate copy.**

### Layer 1 — Grammatical & orthographic correctness as an engineering system (technical moat)
LLMs produce *plausible* Serbian but break on:
- Case agreement across **7 падежи**
- Gender agreement (adj↔noun): "crn**a** majic**a**" vs "crn**i** kaiš"
- Number/quantity forms: 1 / 2–4 / 5+ ("1 proizvod, 2 proizvoda, 5 proizvoda")
- **ćirilica ↔ latinica** transliteration preserving digraphs (nj, lj, dž) and leaving foreign
  brand/model strings untouched ("iPhone" must NOT become "ајПхоне")

Build a **validation + correction layer** *after* generation that guarantees copy-editor-grade
output in **both scripts from a single generation**. No global tool will rebuild its pipeline
for one small market.

### Layer 2 — Attribute-grounded generation, not free generation (trust + compliance moat)
Constrain generation to **assert only attributes present in structured product data** — no
hallucinated "water-resistant to 50m." Ship a **claims-provenance view**: every factual
sentence maps to a source attribute; unsupported claims are flagged. Enterprise pitch: *fewer
returns, no false-advertising exposure under 88/2021.* Reframes you from marketing toy →
risk-reduction tool legal/ops also wants.

### Layer 3 — Domestic-platform integration global players will never build (distribution moat)
They integrate Shopify/Woo/Akeneo. Zero incentive to integrate **Selltico, TAU Commerce**, or
bespoke Magento/Woo builds the Serbian enterprise tier runs on. Unglamorous, and the real moat.

**Honest defensibility hierarchy: Layer 3 > Layer 1 > Layer 2.** Language correctness is the
*wedge + marketing story*; platform lock-in + being physically present for a 6-figure-SKU
migration is what keeps you in the account.

---

## 3. Positioning & ICP

**Do NOT** position as "AI piše opise."

**Position as:**
> **"Ispravni opisi proizvoda na srpskom — na ćirilici i latinici, bez grešaka i bez lažnih
> tvrdnji, za ceo katalog."**

**ICP (sharp):** Ecommerce director / catalog (PIM) manager at a Serbian retailer with
**30,000–800,000 SKUs**, electronics or fashion, on Magento or WooCommerce (often + a domestic
layer), with manufacturer-fed or empty descriptions, a returns problem, and an internal ćirilica
debate.

**Named targets to study:** Shoppster, Gigatron, Tehnomanija, Sport Vision, Forma Ideale.

**Buyer's three pains, in their language:**
1. "Pola kataloga nema opis ili ima isti kopiran tekst."
2. "Ne stižemo da pišemo, a vraćaju nam robu."
3. "Treba nam i ćirilica i latinica i nema ko to da radi."

---

## 4. Pricing & unit economics

High-ticket B2B — **not** $0.75/product (800k SKUs × $0.75 = $600k, absurd, anchors you as a
commodity).

| Tier | What | Price |
|------|------|-------|
| **Pilot / Proof** | 5,000–20,000 SKU batch + 1 connector + correctness QA report. Paid; filters tire-kickers, funds the build. | €2,500–€5,000 fixed |
| **Annual platform license** ≤50k SKU | Dual-script output, correctness validation, claims-provenance, 1 connector. Re-gen included. | ~€12k/yr |
| **Annual platform license** ≤200k SKU | Same, larger catalog. | ~€24k/yr |
| **Annual platform license** 200k+ SKU | Same, enterprise. | €48k+/yr |
| **Setup/migration** | Custom domestic-platform connector. Real eng + switching-cost moat. | €3k–€10k one-time |

Sell **catalog state, not per-call credits** — buyers hate metered anxiety.

**Margin note:** COGS = LLM tokens + correction layer (cheap, runs once per product, cached).
At a €24k account (~150k descriptions/yr), token cost is low three-figure euros. Gross margin
fine. **Real cost center = integration engineering + Serbian-language QA**, not inference.
Budget headcount there.

---

## 5. Build sequence

### Phase 0 — Correctness core (weeks 1–6). Build the moat, not a product yet.
Standalone Serbian post-processor:
- (a) latinica↔ćirilica transliterator with brand/model-number protection + digraph handling
- (b) gender/case/number agreement validator + correction pass
- (c) claims-extractor that diffs generated sentences vs input attribute set, flags unsupported

**Kill criterion:** native copy editor reviews 200 generated+corrected products →
**<3% agreement error**, **0% transliteration error on protected terms**. If you can't hit
transliteration 0%, the moat is fake — **stop**.

### Phase 1 — Batch pipeline + one connector (weeks 7–14).
CSV/XLSX in → attribute-grounded generation → correctness layer → dual-script out → provenance
report. Build **one** connector: **WooCommerce first** (most common, REST API, lowest effort),
Magento second. Run the paid pilot.

### Phase 2 — Domestic platform connector + review UI (weeks 15–24).
**Selltico or TAU Commerce** native integration (distribution moat — prioritize whichever first
two pilots use). Add human-in-the-loop review/approval queue — enterprise teams will NOT publish
unreviewed AI copy to 800k pages.

### Kill criterion for the whole venture
Same discipline as Sinhro: **3 paid pilots from named Serbian retailers before Phase 2
engineering.** Can't get three €2.5k+ pilots from a market this small and concentrated → the
wedge isn't real and building won't fix it.

---

## 6. Why this wins (and the honest risk)

**Wins because** you converted a commodity into three things a global incumbent structurally
won't replicate for a 7M-person market: deterministic dual-script Serbian correctness,
claims-grounded compliance tied to a specific local law, and native integration with platforms
they've never heard of.

**Risk I won't soften:** the market is small and buyer count tiny — maybe **30–50 retailers**
with catalogs big enough to pay €24k/yr. This is a **services-flavored, lifestyle-to-mid
business**, not venture-scale SaaS — *unless* you expand the same engine to
**Croatian / Bosnian / Montenegrin / Macedonian** (near-identical case systems, shared ex-Yu
ecommerce platforms). That's the genuine TAM expansion and the only path to a raise-worthy
number. **Build the agreement/transliteration rules as pluggable per-language from day one**, or
you rewrite the core in year two.

---

## Next actions
- [ ] Draft paid-pilot outreach email to a Gigatron/Shoppster catalog manager
- [ ] Spec the Phase 0 correctness engine in detail
- [ ] Confirm which platforms the first two target retailers actually run (Magento / Woo / Selltico / TAU)
- [ ] Validate €24k/yr willingness-to-pay in 3 discovery calls before writing code
