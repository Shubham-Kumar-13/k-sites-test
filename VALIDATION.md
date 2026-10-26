# Validation of the measured knockout evidence

K-Sites rates a gene from what has been *measured* when the gene is lost. This page checks how far those measurements
can be trusted, how well the estimate for genes without a measurement works, and how informative the pleiotropy score is.
The numbers below are
produced by `tools/evaluate_knockout_evidence.py`; they describe the data version named below and are refreshed with it.

*Generated 2026-10-26 by `tools/evaluate_knockout_evidence.py`.*

## 1. Do the data and the verdicts match published knockouts?

Genes whose knockout outcome was read from the original paper: 12 lethal, 12 viable (16 mouse, 3 zebrafish, 3 fly, 2 worm).

| Organism | Gene | Paper says | Data says | Verdict | Agrees | Paper |
|---|---|---|---|---|---|---|
| mouse | Polb | lethal | lethal (perinatal / neonatal) | AVOID | yes | [Sugo et al. 2000, EMBO J](https://doi.org/10.1093/emboj/19.6.1397) |
| mouse | Tdg | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Cortazar et al. 2011, Nature; Cortellino et al. 2011, Cell](https://doi.org/10.1038/nature09672) |
| mouse | Xrcc1 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Tebbs et al. 1999, Dev Biol](https://doi.org/10.1006/dbio.1999.9232) |
| mouse | Lig4 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Barnes et al. 1998, Curr Biol](https://doi.org/10.1016/s0960-9822(98)00021-9) |
| mouse | Fen1 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Larsen et al. 2003, Mol Cell Biol](https://doi.org/10.1128/MCB.23.15.5346-5353.2003) |
| mouse | Apex1 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Xanthoudakis et al. 1996, PNAS](https://doi.org/10.1073/pnas.93.17.8919) |
| mouse | Lig3 | lethal | subviable (embryonic / prenatal) | HIGH_CONCERN | yes | [Puebla-Osorio et al. 2006, Mol Cell Biol](https://doi.org/10.1128/MCB.26.10.3935-3941.2006) |
| mouse | Pcna | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Roa et al. 2008, PNAS](https://doi.org/10.1073/pnas.0808182105) |
| mouse | Sirt6 | lethal | viable; 1 lethal, 1 subviable of 4 lines | HIGH_CONCERN | yes | [Mostoslavsky et al. 2006, Cell](https://doi.org/10.1016/j.cell.2005.11.044) |
| mouse | Ogg1 | viable | viable | SAFE | yes | [Klungland et al. 1999, PNAS](https://doi.org/10.1073/pnas.96.23.13300) |
| mouse | Ung | viable | viable | CAUTION | yes | [Nilsen et al. 2003, Oncogene](https://doi.org/10.1038/sj.onc.1206860) |
| mouse | Neil1 | viable | viable | CAUTION | yes | [Vartanian et al. 2006, PNAS](https://doi.org/10.1073/pnas.0507444103) |
| mouse | Parp1 | viable | viable; 3 subviable of 10 lines | CAUTION | yes | [Wang et al. 1995, Genes Dev](https://doi.org/10.1101/gad.9.5.509) |
| mouse | Xpa | viable | viable; 1 subviable of 4 lines | CAUTION | yes | [de Vries et al. 1995, Nature](https://doi.org/10.1038/377169a0) |
| mouse | Smug1 | viable | viable | SAFE | yes | [Kemmerich et al. 2012, Nucleic Acids Res](https://doi.org/10.1093/nar/gks259) |
| mouse | Nthl1 | viable | viable | SAFE | yes | [Takao et al. 2002, EMBO J](https://doi.org/10.1093/emboj/cdf350) |
| zebrafish | smn1 | lethal | lethal (larval, pupal or juvenile stage) | AVOID | yes | [Boon et al. 2009, Hum Mol Genet](https://doi.org/10.1093/hmg/ddp310) |
| zebrafish | ar | viable | viable | SAFE | yes | [Tang et al. 2018, Biol Reprod](https://doi.org/10.1093/biolre/iox165) |
| zebrafish | lhb | viable | viable | SAFE | yes | [Chu et al. 2014, Mol Endocrinol](https://doi.org/10.1210/me.2014-1061) |
| fly | Egfr | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Clifford and Schupbach 1989, Genetics](https://doi.org/10.1093/genetics/123.4.771) |
| fly | Wnt2 | viable | viable | CAUTION | yes | [Kozopas et al. 1998, Genes Dev](https://doi.org/10.1101/gad.12.8.1155) |
| fly | Nos | viable | viable | SAFE | yes | [Yakubovich et al. 2010, Curr Biol](https://doi.org/10.1016/j.cub.2009.12.011) |
| worm | skn-1 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Bowerman et al. 1992, Cell](https://doi.org/10.1016/0092-8674(92)90078-q) |
| worm | fem-1 | viable | viable | CAUTION | yes | [Doniach and Hodgkin 1984, Dev Biol](https://doi.org/10.1016/0012-1606(84)90077-0) |

- Lethal knockouts flagged (AVOID or HIGH_CONCERN): **12 of 12**
- Viable knockouts not rated AVOID: **12 of 12**

## 2. Do the two sources agree with each other?

Genes with a call from both the MGI literature curation and the IMPC screen: **7,514**.

|  | IMPC: lethal | IMPC: subviable | IMPC: viable |
|---|---|---|---|
| MGI: lethal | 1979 | 145 | 80 |
| MGI: subviable | 20 | 453 | 207 |
| MGI: viable | 33 | 103 | 4494 |

- The two sources give the same call for **92.2%** of these genes.
- Of the 2,032 genes that the IMPC screen found lethal, MGI records a lethal or subviable knockout for **99.9%** (a lethal gene is therefore rarely rated safe).
- Of the 4,781 genes the IMPC screen found viable, MGI calls **1.7%** lethal (often a classical null allele that the screen's allele did not reproduce).

## 3. Do mouse lethality and human cell essentiality agree?

Human genes with a one-to-one mouse ortholog and a DepMap result: **12,825**.

|  | essential in most human cell lines | not essential in most human cell lines |
|---|---|---|
| lethal in the mouse knockout | 1034 | 2402 |
| viable or subviable in the mouse knockout | 77 | 9312 |

- 93.1% of the genes that are essential in most cell lines are lethal in the mouse; 69.9% of the mouse-lethal genes are *not* essential in cell lines (they are needed for development, not for every cell).
- Odds ratio 51.7 (95% interval 40.9 to 65.5): the two independent measurements agree far more often than chance, and they are different enough that both are shown.

## 4. How many genes are covered?

| Data | Genes | Detail |
|---|---|---|
| Mouse knockout (MGI and IMPC) | 14,381 | 3,591 lethal, 1,109 subviable, 9,681 viable |
| Human protein-coding genes with a mouse-ortholog knockout | 13,649 of 19,299 | 70.7% |
| Human protein-coding genes with a DepMap cell-line result | 17,855 of 19,299 | 92.5% |
| Human protein-coding genes with at least one of the two | 18,338 of 19,299 | 95.0% |
| Rattus norvegicus (ortholog-knockout) | 13,793 |  |
| Saccharomyces cerevisiae S288C (knockout, paralogs) | 11,443 |  |
| Caenorhabditis elegans (knockout, ortholog-knockout, paralogs) | 6,830 | measured: 4,072 lethal, 0 subviable, 33 viable; the other genes carry the mouse-ortholog hint |
| Drosophila melanogaster (knockout, ortholog-knockout, paralogs) | 8,563 | measured: 3,950 lethal, 390 subviable, 592 viable; the other genes carry the mouse-ortholog hint |
| Danio rerio (knockout, ortholog-knockout, paralogs) | 14,125 | measured: 396 lethal, 101 subviable, 457 viable; the other genes carry the mouse-ortholog hint |
| Xenopus tropicalis (ortholog-knockout) | 12,067 |  |

Data version 2026-10-26.

## 5. How good is the estimate for genes without a knockout result?

Most genes were never knocked out in a mouse. For them K-Sites estimates the chance that the knockout is lethal from the measurements of the human ortholog (share of cancer cell lines that need the gene, how rarely people carry loss-of-function variants, tissue expression, close paralogs). The model was fitted on **12,234** mouse genes with a known outcome (3,502 lethal, 8,732 viable) and tested on genes it had not seen (5-fold cross-validation).

- Area under the ROC curve: **0.835** (0.5 is a coin flip, 1.0 is perfect).
- Flagging the genes estimated at 0.3 or higher finds **65.1%** of the lethal genes and wrongly flags **13.6%** of the viable ones. For comparison, the keyword prediction in section 6 found 23% and wrongly flagged 13%.

| Estimated band | Tested genes | Of these, lethal in the mouse | Mouse genes without a knockout result in this band |
|---|---|---|---|
| likely lethal (estimate 0.5 or higher) | 1,845 | 88.1% | 769 |
| possibly lethal (0.3 to 0.5) | 1,625 | 40.2% | 315 |
| unlikely to be lethal (under 0.3) | 8,764 | 14.0% | 3,096 |

- Human genes with an estimate (no mouse knockout result): 4,180.
- The genes that were tested in mice are not a random sample: researchers knock out genes they already suspect to matter, so the lethal share among never-tested genes is probably lower than the shares above. The estimate is shown as an estimate, never rates a gene better than CAUTION, and a measurement always replaces it.

## 6. How good is the old keyword prediction?

Most genes were never knocked out in a mouse. For them K-Sites estimates the chance that the knockout is lethal from the measurements of the human ortholog (share of cancer cell lines that need the gene, how rarely people carry loss-of-function variants, tissue expression, close paralogs). The model was fitted on **12,021** mouse genes with a known outcome (3,451 lethal, 8,570 viable) and tested on genes it had not seen (5-fold cross-validation).

- Area under the ROC curve: **0.836** (0.5 is a coin flip, 1.0 is perfect).
- Flagging the genes estimated at 0.3 or higher finds **65.1%** of the lethal genes and wrongly flags **13.6%** of the viable ones. For comparison, the keyword prediction in section 6 found 23% and wrongly flagged 13%.

| Estimated band | Tested genes | Of these, lethal in the mouse | Mouse genes without a knockout result in this band |
|---|---|---|---|
| likely lethal (estimate 0.5 or higher) | 1,812 | 88.2% | 726 |
| possibly lethal (0.3 to 0.5) | 1,598 | 40.4% | 306 |
| unlikely to be lethal (under 0.3) | 8,611 | 14.0% | 2,877 |

- Human genes with an estimate (no mouse knockout result): 3,909.
- The genes that were tested in mice are not a random sample: researchers knock out genes they already suspect to matter, so the lethal share among never-tested genes is probably lower than the shares above. The estimate is shown as an estimate, never rates a gene better than CAUTION, and a measurement always replaces it.

## 7. Does the pleiotropy score track what is measured?

**all evidence**: 13,733 mouse genes with GO biological-process terms and a measured knockout.

- Rank correlation between the pleiotropy score and the number of organ systems with a knockout phenotype: **0.34**.
- Area under the ROC curve for telling lethal from viable knockouts: **0.61** (12,661 genes).

| Pleiotropy score | Genes | Lethal knockouts | Mean organ systems affected |
|---|---|---|---|
| 0 to 0.01 | 1,603 | 13.8% | 2.6 |
| 0.01 to 3 | 1,438 | 21.1% | 2.7 |
| 3 to 6 | 2,358 | 25.0% | 3.2 |
| 6 to 9 | 2,964 | 28.0% | 3.8 |
| 9 to 10 | 4,298 | 36.7% | 5.6 |

**experimental evidence only**: 8,990 mouse genes with GO biological-process terms and a measured knockout.

- Rank correlation between the pleiotropy score and the number of organ systems with a knockout phenotype: **0.32**.
- Area under the ROC curve for telling lethal from viable knockouts: **0.58** (8,224 genes).

| Pleiotropy score | Genes | Lethal knockouts | Mean organ systems affected |
|---|---|---|---|
| 0 to 0.01 | 1,890 | 27.0% | 3.5 |
| 0.01 to 3 | 1,285 | 23.3% | 3.9 |
| 3 to 6 | 1,663 | 25.3% | 4.3 |
| 6 to 9 | 1,634 | 30.4% | 4.9 |
| 9 to 10 | 1,752 | 42.4% | 7.0 |

The score rises with both measures, so it carries real signal, but it is modest: it is a count of annotated roles and genes that are heavily studied have more annotations. Treat it as a hint about broad effects, not as a replacement for the knockout measurement.

## 8. Do the knockout results of every organism agree with the human core-essential genes?

| Organism | Core-essential orthologs with a result | called lethal | Non-essential orthologs with a result | called lethal | Separation (points) |
|---|---|---|---|---|---|
| Mouse | 431 | 96.1% | 489 | 8.6% | 87 |
| Yeast | 524 | 61.3% | 48 | 12.5% | 49 |
| Zebrafish | 37 | 89.2% | 29 | 27.6% | 62 |
| Fly | 220 | 95.5% | 64 | 81.2% | 14 |
| Worm | 472 | 100.0% | 49 | 87.8% | 12 |

A large separation means the organism's lethal calls tell essential genes from non-essential ones. Mouse (a systematic screen
plus the literature) separates them best. **For fly and worm the separation is small because their databases record lethal
mutants far more often than viable ones**: a gene is in the database mostly because a mutant was found that died. For them a
lethal call is a hint to confirm in the literature, not a measurement of how many genes are essential, and the share of
"non-essential" genes called lethal is inflated by that selection, not necessarily by errors. The site says so before a fly,
worm or zebrafish run.

## What these checks do not show

- **They do not prove that a knockout will work in your hands.** A measurement says what happened in the published mice, yeast
  or cell lines; strain, allele, cell type, culture conditions and the way the gene is removed all matter.
- **The two mouse sources are not fully independent.** IMPC alleles are often knockout-first or deletion alleles that can be
  hypomorphic, while literature nulls are often classical alleles; where they disagree the report shows both and rates the
  gene at least HIGH_CONCERN if any line was lethal.
- **Absence of a lethality annotation is weak evidence of viability.** K-Sites therefore counts a knockout as viable only when
  the null animals were examined as young or adult animals (or declared normal); genes with only embryonic findings stay
  "not verified".
- **Cell-line essentiality comes from cancer cell lines** (DepMap 24Q4). Primary cells, stem cells and other cell types can differ.
- **Zebrafish, fly and worm are measured only for the genes their community databases cover.** ZFIN, FlyBase and WormBase
  curate mutants that were studied for a reason, so the covered genes are biased towards interesting phenotypes (and, for
  zebrafish, towards recent CRISPR mutants); fish with morpholinos, transgenes or heterozygous genotypes are left out. WormBase
  does not say which alleles are null, so a gene is called viable only when two or more alleles are reported not lethal, and a
  lethal call that rests on RNAi alone is marked as such. Genes without a measurement of their own, Xenopus, and every plant
  or other organism have no measured data; for zebrafish, fly, worm and Xenopus the knockout of the mouse ortholog is shown as
  a hint, never as a measurement. Arabidopsis has no openly licensed machine-readable knockout resource that could be used.

## How to reproduce

```bash
python tools/build_evidence_data.py --out .cache/evidence-out        # builds the data files (downloads the sources once)
python tools/evaluate_knockout_evidence.py --out VALIDATION.md       # re-runs sections 1-5 and 7
python tools/evaluate_knockout_evidence.py --predictor 60            # adds section 6 (needs the network, about 20 minutes)
python -m pytest tests/test_paper_truth.py                            # the published-knockout check as a unit test
```

The published-knockout list is `tests/fixtures/benchmark/paper_truth.json`; every entry cites the paper whose abstract was read.
