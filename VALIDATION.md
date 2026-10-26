# Validation of the measured knockout evidence

K-Sites rates a gene from what has been *measured* when the gene is lost. This page checks how far those measurements
can be trusted, and how the keyword prediction that is used where nothing is measured performs. The numbers below are
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
| Caenorhabditis elegans (knockout, ortholog-knockout) | 6,830 | measured: 4,072 lethal, 0 subviable, 33 viable; the other genes carry the mouse-ortholog hint |
| Drosophila melanogaster (knockout, ortholog-knockout) | 8,563 | measured: 3,950 lethal, 390 subviable, 592 viable; the other genes carry the mouse-ortholog hint |
| Danio rerio (knockout, ortholog-knockout) | 14,125 | measured: 396 lethal, 101 subviable, 457 viable; the other genes carry the mouse-ortholog hint |
| Xenopus tropicalis (ortholog-knockout) | 12,067 |  |

Data version 2026-10-26.

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
python tools/evaluate_knockout_evidence.py --out VALIDATION.md       # re-runs sections 1-4
python tools/evaluate_knockout_evidence.py --predictor 60            # adds section 5 (needs the network, about 20 minutes)
python -m pytest tests/test_paper_truth.py                            # the published-knockout check as a unit test
```

The published-knockout list is `tests/fixtures/benchmark/paper_truth.json`; every entry cites the paper whose abstract was read.
