# Validation of the measured knockout evidence

K-Sites rates a gene from what has been *measured* when the gene is lost. This page checks how far those measurements
can be trusted, and how the keyword prediction that is used where nothing is measured performs. The numbers below are
produced by `tools/evaluate_knockout_evidence.py`; they describe the data version named below and are refreshed with it.

*Generated 2026-10-25 by `tools/evaluate_knockout_evidence.py`.*

## 1. Do the data and the verdicts match published knockouts?

Genes whose knockout outcome was read from the original paper: 9 lethal, 7 viable.

| Gene | Paper says | Data says | Verdict | Agrees | Paper |
|---|---|---|---|---|---|
| Polb | lethal | lethal (perinatal / neonatal) | AVOID | yes | [Sugo et al. 2000, EMBO J](https://doi.org/10.1093/emboj/19.6.1397) |
| Tdg | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Cortazar et al. 2011, Nature; Cortellino et al. 2011, Cell](https://doi.org/10.1038/nature09672) |
| Xrcc1 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Tebbs et al. 1999, Dev Biol](https://doi.org/10.1006/dbio.1999.9232) |
| Lig4 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Barnes et al. 1998, Curr Biol](https://doi.org/10.1016/s0960-9822(98)00021-9) |
| Fen1 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Larsen et al. 2003, Mol Cell Biol](https://doi.org/10.1128/MCB.23.15.5346-5353.2003) |
| Apex1 | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Xanthoudakis et al. 1996, PNAS](https://doi.org/10.1073/pnas.93.17.8919) |
| Lig3 | lethal | subviable (embryonic / prenatal) | HIGH_CONCERN | yes | [Puebla-Osorio et al. 2006, Mol Cell Biol](https://doi.org/10.1128/MCB.26.10.3935-3941.2006) |
| Pcna | lethal | lethal (embryonic / prenatal) | AVOID | yes | [Roa et al. 2008, PNAS](https://doi.org/10.1073/pnas.0808182105) |
| Sirt6 | lethal | viable; 1 lethal, 1 subviable of 4 lines | HIGH_CONCERN | yes | [Mostoslavsky et al. 2006, Cell](https://doi.org/10.1016/j.cell.2005.11.044) |
| Ogg1 | viable | viable | SAFE | yes | [Klungland et al. 1999, PNAS](https://doi.org/10.1073/pnas.96.23.13300) |
| Ung | viable | viable | CAUTION | yes | [Nilsen et al. 2003, Oncogene](https://doi.org/10.1038/sj.onc.1206860) |
| Neil1 | viable | viable | CAUTION | yes | [Vartanian et al. 2006, PNAS](https://doi.org/10.1073/pnas.0507444103) |
| Parp1 | viable | viable; 3 subviable of 10 lines | CAUTION | yes | [Wang et al. 1995, Genes Dev](https://doi.org/10.1101/gad.9.5.509) |
| Xpa | viable | viable; 1 subviable of 4 lines | CAUTION | yes | [de Vries et al. 1995, Nature](https://doi.org/10.1038/377169a0) |
| Smug1 | viable | viable | SAFE | yes | [Kemmerich et al. 2012, Nucleic Acids Res](https://doi.org/10.1093/nar/gks259) |
| Nthl1 | viable | viable | SAFE | yes | [Takao et al. 2002, EMBO J](https://doi.org/10.1093/emboj/cdf350) |

- Lethal knockouts flagged (AVOID or HIGH_CONCERN): **9 of 9**
- Viable knockouts not rated AVOID: **7 of 7**

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

Human genes with a one-to-one mouse ortholog and a DepMap result: **12,630**.

|  | essential in most human cell lines | not essential in most human cell lines |
|---|---|---|
| lethal in the mouse knockout | 1011 | 2380 |
| viable or subviable in the mouse knockout | 69 | 9170 |

- 93.6% of the genes that are essential in most cell lines are lethal in the mouse; 70.2% of the mouse-lethal genes are *not* essential in cell lines (they are needed for development, not for every cell).
- Odds ratio 56.1 (95% interval 43.8 to 71.8): the two independent measurements agree far more often than chance, and they are different enough that both are shown.

## 4. How many genes are covered?

| Data | Genes | Detail |
|---|---|---|
| Mouse knockout (MGI and IMPC) | 14,381 | 3,591 lethal, 1,109 subviable, 9,681 viable |
| Human protein-coding genes with a mouse-ortholog knockout | 13,649 of 19,299 | 70.7% |
| Human protein-coding genes with a DepMap cell-line result | 17,855 of 19,299 | 92.5% |
| Human protein-coding genes with at least one of the two | 18,338 of 19,299 | 95.0% |
| Rattus norvegicus (ortholog-knockout) | 13,793 |  |
| Saccharomyces cerevisiae S288C (knockout) | 11,443 |  |
| Caenorhabditis elegans (ortholog-knockout) | 4,154 |  |
| Drosophila melanogaster (ortholog-knockout) | 4,842 |  |
| Danio rerio (ortholog-knockout) | 13,819 |  |
| Xenopus tropicalis (ortholog-knockout) | 12,067 |  |

Data version 2026-10-25.

## 5. How good is the fallback prediction where nothing is measured?

Random sample of 60 mouse genes with a clear measured outcome (seed 7).

|  | predicted lethal | predicted not lethal | no prediction |
|---|---|---|---|
| measured lethal | 7 | 5 | 18 |
| measured viable | 4 | 3 | 23 |

- Sensitivity: 23.3% of the lethal genes were predicted lethal.
- False alarms: 13.3% of the viable genes were predicted lethal.
- No prediction at all: 68.3% of the genes.

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
- **Species other than human, mouse, rat and yeast have no measured data here.** Zebrafish, fly, worm and Xenopus only get the
  knockout of their mouse ortholog as a hint, never a measurement.

## How to reproduce

```bash
python tools/build_evidence_data.py --out .cache/evidence-out        # builds the data files (downloads the sources once)
python tools/evaluate_knockout_evidence.py --out VALIDATION.md       # re-runs sections 1-4
python tools/evaluate_knockout_evidence.py --predictor 60            # adds section 5 (needs the network, about 20 minutes)
python -m pytest tests/test_paper_truth.py                            # the published-knockout check as a unit test
```

The published-knockout list is `tests/fixtures/benchmark/paper_truth.json`; every entry cites the paper whose abstract was read.
