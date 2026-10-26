"""
Help content and documentation for K-Sites analytical terms
"""

ANALYTICAL_TERMS = {
    "pleiotropy_score": {
        "title": "Pleiotropy Score",
        "icon": "fa-project-diagram",
        "short_description": "Measures how many different biological processes a gene is involved in",
        "detailed_explanation": """
            <p>The <strong>Pleiotropy Score</strong> quantifies the degree to which a gene influences multiple, 
            seemingly unrelated phenotypic traits or biological processes.</p>
            
            <h6>How it's calculated:</h6>
            <ul>
                <li>Counts the number of Biological Process GO terms associated with the gene</li>
                <li>Reports the number of KEGG pathways the gene belongs to</li>
                <li>Uses exponential decay scoring to penalize highly pleiotropic genes</li>
            </ul>
            
            <h6>Score Range:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr><td class="text-success"><strong>0-2</strong></td><td>Highly specific - excellent CRISPR target</td></tr>
                    <tr><td class="text-info"><strong>2-5</strong></td><td>Moderately specific - good target</td></tr>
                    <tr><td class="text-warning"><strong>5-8</strong></td><td>Broadly involved - use with caution</td></tr>
                    <tr><td class="text-danger"><strong>8-10</strong></td><td>Highly pleiotropic - may cause unintended effects</td></tr>
                </table>
            </div>
            
            <h6>Max pleiotropy (cutoff):</h6>
            <p>The score is always on a 0-10 scale. The <strong>max pleiotropy</strong> setting is a cutoff on that
            score: genes scoring above it are left out. 0 keeps only the most specific genes, 10 keeps everything.</p>
            
            <h6>Why it matters:</h6>
            <p>Genes with low pleiotropy scores are preferred for CRISPR experiments because knocking them out 
            is less likely to cause widespread, unpredictable phenotypic changes. High pleiotropy may indicate 
            essential genes or hub genes in regulatory networks.</p>
        """,
        "reference": "Based on GO Biological Process annotations"
    },
    
    "specificity_score": {
        "title": "Specificity Score",
        "icon": "fa-bullseye",
        "short_description": "Inverse measure of pleiotropy - higher is more specific",
        "detailed_explanation": """
            <p>The <strong>Specificity Score</strong> is calculated as <code>10 - pleiotropy_score</code>, 
            providing an intuitive measure where higher values indicate more specific genes.</p>
            
            <h6>Interpretation:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr><td class="text-success"><strong>8-10</strong></td><td>Highly specific to your pathway of interest</td></tr>
                    <tr><td class="text-info"><strong>5-8</strong></td><td>Moderately specific</td></tr>
                    <tr><td class="text-warning"><strong>2-5</strong></td><td>Low specificity</td></tr>
                    <tr><td class="text-danger"><strong>0-2</strong></td><td>Very broad involvement</td></tr>
                </table>
            </div>
            
            <h6>Usage:</h6>
            <p>Use this score to quickly identify the most specific targets for your CRISPR screen. 
            Genes with specificity scores above 7 are generally considered safe candidates for knockout studies.</p>
        """,
        "reference": "Derived from pleiotropy score calculation"
    },
    
    "composite_score": {
        "title": "Composite Score",
        "icon": "fa-star",
        "short_description": "Weighted combination of specificity, evidence quality, and literature support",
        "detailed_explanation": """
            <p>The <strong>Composite Score</strong> integrates multiple factors to rank genes by their 
            suitability as CRISPR targets.</p>
            
            <h6>Formula:</h6>
            <div class="alert alert-light">
                <code>Composite = (Specificity × 0.4) + (Evidence Quality × 0.3) + (Literature Score × 0.2) + (Conservation × 0.1)</code>
            </div>
            
            <h6>Components:</h6>
            <ul>
                <li><strong>Specificity (40%):</strong> Based on pleiotropy score</li>
                <li><strong>Evidence Quality (30%):</strong> Experimental vs computational evidence</li>
                <li><strong>Literature Score (20%):</strong> PubMed citation count and relevance</li>
                <li><strong>Conservation (10%):</strong> Cross-species conservation of gene function</li>
            </ul>
            
            <h6>Range:</h6>
            <p>0-10 scale, where higher scores indicate better overall candidates for CRISPR targeting.</p>
        """,
        "reference": "Multi-factorial weighted scoring algorithm"
    },
    
    "evidence_quality": {
        "title": "Evidence Quality",
        "icon": "fa-check-double",
        "short_description": "Reliability of GO annotations based on evidence codes",
        "detailed_explanation": """
            <p>The <strong>Evidence Quality</strong> score reflects the reliability of Gene Ontology annotations 
            based on the types of evidence supporting them.</p>
            
            <h6>Evidence Code Hierarchy:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr class="table-success">
                        <td><strong>EXP</strong></td>
                        <td>Experimental</td>
                        <td>Direct experimental evidence (highest quality)</td>
                    </tr>
                    <tr class="table-success">
                        <td><strong>IDA</strong></td>
                        <td>Direct Assay</td>
                        <td>Direct experimental assay</td>
                    </tr>
                    <tr class="table-success">
                        <td><strong>IMP</strong></td>
                        <td>Mutant Phenotype</td>
                        <td>Evidence from mutant studies</td>
                    </tr>
                    <tr class="table-info">
                        <td><strong>ISO</strong></td>
                        <td>Sequence Orthology</td>
                        <td>Inferred from orthologs</td>
                    </tr>
                    <tr class="table-warning">
                        <td><strong>IEA</strong></td>
                        <td>Electronic Annotation</td>
                        <td>Computational prediction (lowest quality)</td>
                    </tr>
                </table>
            </div>
            
            <h6>Score Calculation:</h6>
            <p>Weighted average based on the proportion of experimental vs computational evidence codes 
            associated with the gene's GO annotations.</p>
        """,
        "reference": "Gene Ontology Evidence Codes (https://geneontology.org/docs/guide-go-evidence-codes/)"
    },
    
    "safety_level": {
        "title": "Safety Level",
        "icon": "fa-shield-alt",
        "short_description": "Overall safety recommendation based on multiple risk factors",
        "detailed_explanation": """
            <p>The <strong>Safety Level</strong> provides an overall assessment of the risk associated 
            with knocking out a particular gene.</p>
            
            <h6>Safety Levels:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr class="table-success">
                        <td><strong>SAFE</strong></td>
                        <td>Safe to delete - standard knockout acceptable</td>
                    </tr>
                    <tr class="table-info">
                        <td><strong>CAUTION</strong></td>
                        <td>Generally safe - validation recommended</td>
                    </tr>
                    <tr class="table-warning">
                        <td><strong>MODERATE_CONCERN</strong></td>
                        <td>Use with caution - heterozygous or validated knockout suggested</td>
                    </tr>
                    <tr class="table-danger">
                        <td><strong>HIGH_CONCERN / AVOID</strong></td>
                        <td>High risk - conditional knockout, CRISPRi or another strategy preferred</td>
                    </tr>
                </table>
            </div>
            
            <h6>What the level rests on:</h6>
            <ol>
                <li><strong>Measured knockout evidence</strong> comes first: whether the knockout organism or the
                    cultured human cells survive (see <a href="#knockout_evidence">Measured knockout evidence</a>).
                    A gene whose knockout is lethal is never rated safe, however specific it looks.</li>
                <li>The <strong>pleiotropy score</strong> adds caution to a viable gene that has many annotated roles
                    (above 5: validate first), because its phenotypes will be broad.</li>
                <li>Without any measurement the verdict can only rest on annotations and keyword predictions, and it is
                    <strong>never better than CAUTION</strong>. The report says "Not verified" for such genes.</li>
            </ol>
            <p>Genes are listed safest first, then by composite score. Each gene card says which measurement decided
            the verdict.</p>
        """,
        "reference": "K-Sites integrated safety assessment algorithm"
    },

    "knockout_evidence": {
        "title": "Measured knockout evidence",
        "icon": "fa-vial",
        "short_description": "What has actually been measured when the gene is lost",
        "detailed_explanation": """
            <p>K-Sites does not guess how harmful a knockout is where somebody has already measured it. For each gene it
            looks up:</p>
            <ul>
                <li><strong>Whole-organism knockout.</strong> Mouse: the literature curated by MGI (knockout alleles in
                    homozygous mice) and the systematic IMPC viability screen. Human and rat genes use the knockout of
                    their one-to-one mouse ortholog (Alliance of Genome Resources). Yeast: SGD deletion phenotypes. Zebrafish:
                    ZFIN mutant phenotypes (clean homozygous mutants only). Fly: FlyBase allele lethality phenotypes.
                    Worm: WormBase allele and RNAi lethal / sterile phenotypes. For the genes of zebrafish, fly and worm
                    that these databases do not cover, and for Xenopus, the mouse ortholog's knockout is shown as a hint
                    only. Plants and other organisms have no measured data.
                    The result is <em>lethal</em> (with the stage of death), <em>subviable</em> (fewer homozygotes than
                    expected) or <em>viable</em>, with the number of knockout lines behind it and links to the papers.</li>
                <li><strong>Human cell lines.</strong> The percentage of 1,178 cancer cell lines in which a CRISPR knockout
                    kills the cells (DepMap 24Q4). <em>Essential</em>: most lines or DepMap's common essentials;
                    <em>sometimes essential</em>: 10-50%; <em>rarely essential</em>: under 10%.</li>
                <li><strong>Tolerance in people</strong> (gnomAD LOEUF), <strong>tissue expression</strong> (GTEx; a
                    tissue-restricted gene can be removed in those tissues only) and <strong>close paralogs</strong>
                    (Ensembl; they can take over the gene's work and hide the phenotype).</li>
            </ul>
            <h6>How to read the label on each gene:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr><td><strong>Measured</strong></td><td>the organism or the cells were tested for this gene</td></tr>
                    <tr><td><strong>Measured in the mouse ortholog</strong></td><td>the mouse gene was tested; the result is carried over to the human or rat gene</td></tr>
                    <tr><td><strong>Predicted from the literature</strong></td><td>nothing was measured; a keyword model read abstracts (experimental, see below)</td></tr>
                    <tr><td><strong>Not verified</strong></td><td>no measurement and no prediction: check MGI, IMPC or DepMap yourself</td></tr>
                </table>
            </div>
            <h6>Things to know:</h6>
            <ul>
                <li>When knockout lines disagree (for example a classical null is lethal but a different allele or strain is
                    viable) the report says so and rates the gene at least HIGH_CONCERN if any line was lethal.</li>
                <li>"Viable" does not mean "unaffected": the organ systems with a reported phenotype are listed, and
                    a shortened lifespan or infertility lowers the rating to CAUTION.</li>
                <li>A mouse-lethal gene can be fine in cultured cells (it is needed for development, not in every cell),
                    so both results are always shown.</li>
                <li>The data come from the files published with this site, refreshed monthly. A "Data sources" list with the
                    version is part of every report.</li>
            </ul>
        """,
        "reference": "MGI, IMPC, Alliance of Genome Resources, SGD, ZFIN, FlyBase, WormBase, DepMap 24Q4, gnomAD v4.1, GTEx v8, Ensembl Compara; checks on the Validation page"
    },

    "knockout_context": {
        "title": "What will you knock out?",
        "icon": "fa-flask",
        "short_description": "Cultured cells or a whole organism: it decides which measurement the verdict follows",
        "detailed_explanation": """
            <p>The same gene can be harmless to knock out in a cell line and impossible to knock out in an animal.
            <em>TDG</em> and <em>POLB</em> are good examples: mouse embryos lacking them die, but human cell lines
            tolerate their loss.</p>
            <ul>
                <li><strong>Cultured cells</strong> (the default for human): the verdict follows the DepMap CRISPR screens.
                    The mouse result is still shown, as a reminder that an animal model would need a conditional allele.</li>
                <li><strong>Whole organism</strong> (the default for mouse, rat, yeast, zebrafish, fly, worm and everything else): the verdict
                    follows the knockout organism (or the mouse ortholog).</li>
            </ul>
            <p>Both measurements are shown for every gene whichever you choose; the card marks the one that decides
            the verdict.</p>
        """,
        "reference": "DepMap (cell lines); MGI / IMPC / SGD / ZFIN / FlyBase / WormBase (organisms)"
    },

    "phenotype_prediction": {
        "title": "RAG Phenotype Prediction (experimental)",
        "icon": "fa-brain",
        "short_description": "A keyword model that guesses the phenotype from abstracts, only where nothing is measured",
        "detailed_explanation": """
            <p><strong>Retrieval-Augmented Generation (RAG)</strong> phenotype prediction uses AI to 
            analyze scientific literature and predict the likely phenotypic consequences of gene knockout.</p>
            
            <h6>How it works:</h6>
            <ol>
                <li>Queries PubMed for papers about the target gene</li>
                <li>Retrieves relevant abstracts and metadata</li>
                <li>Uses language models to extract phenotype information</li>
                <li>Classifies severity: LETHAL, SEVERE, MODERATE, MILD, or UNKNOWN</li>
            </ol>
            
            <h6>Severity Categories:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr class="table-danger"><td><strong>LETHAL</strong></td><td>Knockout causes organism death</td></tr>
                    <tr class="table-warning"><td><strong>SEVERE</strong></td><td>Major developmental or physiological defects</td></tr>
                    <tr class="table-info"><td><strong>MODERATE</strong></td><td>Detectable but manageable phenotypes</td></tr>
                    <tr class="table-success"><td><strong>MILD</strong></td><td>Subtle or conditional phenotypes</td></tr>
                    <tr class="table-secondary"><td><strong>UNKNOWN</strong></td><td>Insufficient data for prediction</td></tr>
                </table>
            </div>
            
            <h6>Limitations (measured, not assumed):</h6>
            <p>It is only used for genes without a <a href="#knockout_evidence">measured knockout result</a>, and it
            is switched off by default. We tested it on a random sample of 60 mouse genes whose knockout outcome is known:
            it recognised 7 of the 30 lethal genes, wrongly called 4 of the 30 viable genes lethal, and gave no answer for
            two thirds of the genes (see the <a href="/validation">Validation page</a>). Treat a prediction as a hint to read the papers, not as a result.</p>
        """,
        "reference": "RAG-based NLP pipeline using PubMed and SentenceTransformers"
    },
    
    "conservation_score": {
        "title": "Cross-Species Conservation",
        "icon": "fa-globe",
        "short_description": "Degree to which gene function is conserved across species",
        "detailed_explanation": """
            <p>The <strong>Conservation Score</strong> measures how well a gene's function is preserved 
            across different species, indicating its functional importance.</p>
            
            <h6>How it's calculated:</h6>
            <ul>
                <li>Checks for orthologs in model organisms</li>
                <li>Compares GO term conservation</li>
                <li>Evaluates sequence similarity</li>
            </ul>
            
            <h6>Interpretation:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr><td class="text-info"><strong>0.0-0.3</strong></td><td>Species-specific function</td></tr>
                    <tr><td class="text-success"><strong>0.3-0.7</strong></td><td>Moderately conserved</td></tr>
                    <tr><td class="text-warning"><strong>0.7-1.0</strong></td><td>Highly conserved - likely essential</td></tr>
                </table>
            </div>
            
            <h6>Usage:</h6>
            <p>Highly conserved genes may be essential and more challenging to knockout. 
            Species-specific genes might be better targets for selective studies.</p>
        """,
        "reference": "Cross-species ortholog analysis via UniProt and NCBI"
    }
}


METHODOLOGY_SECTIONS = [
    {
        "title": "Overview",
        "icon": "fa-microscope",
        "content": """
            <p>K-Sites helps you pick a safe gene to delete. It integrates multiple 
            biological databases and literature mining to rank the genes of a biological process by 
            how specific their function is and how risky a knockout is likely to be.</p>
            
            <p>The platform follows a multi-step pipeline from gene discovery to a safety 
            recommendation for each candidate gene.</p>
        """
    },
    {
        "title": "Step 1: Gene Discovery",
        "icon": "fa-search",
        "content": """
            <p>The pipeline begins by querying the <strong>QuickGO</strong> database to retrieve all 
            genes annotated with the selected Gene Ontology (GO) term in the specified organism.</p>
            
            <p>Users can filter by evidence type:</p>
            <ul>
                <li><strong>Experimental:</strong> Only experimentally validated annotations</li>
                <li><strong>Computational:</strong> Includes computational predictions</li>
                <li><strong>All:</strong> All available evidence types</li>
            </ul>
            
            <p>This step typically returns 10-500 genes depending on the GO term specificity.</p>
        """
    },
    {
        "title": "Step 2: Pleiotropy Scoring",
        "icon": "fa-project-diagram",
        "content": """
            <p>Each discovered gene is scored for <strong>pleiotropy</strong> - the degree to which it 
            participates in multiple biological processes.</p>
            
            <p>The scoring algorithm:</p>
            <ol>
                <li>Queries all GO annotations for the gene</li>
                <li>Counts unique Biological Process terms</li>
                <li>Retrieves KEGG pathway memberships (reported as a pathway count)</li>
                <li>Calculates exponential decay score</li>
            </ol>
            
            <p>Genes with low pleiotropy scores are prioritized as they are more likely to produce 
            specific, interpretable phenotypes upon knockout.</p>
        """
    },
    {
        "title": "Step 3: Evidence Quality Assessment",
        "icon": "fa-check-double",
        "content": """
            <p>GO annotations are evaluated based on their <strong>evidence codes</strong>:</p>
            
            <ul>
                <li><strong>Experimental (EXP, IDA, IMP, IGI, IEP):</strong> Direct experimental evidence</li>
                <li><strong>Phylogenetic (IBA, IBD, IKR, IRD):</strong> Evidence from related species</li>
                <li><strong>Computational (ISS, ISO, ISA, ISM, IGC, IBA, IBD):</strong> Predicted annotations</li>
                <li><strong>Author Statements (TAS, NAS):</strong> Non-traceable statements</li>
                <li><strong>Electronic (IEA):</strong> Automated predictions (lowest confidence)</li>
            </ul>
            
            <p>Genes with higher proportions of experimental evidence receive better scores.</p>
        """
    },
    {
        "title": "Step 4: Literature Mining",
        "icon": "fa-book",
        "content": """
            <p>The system queries <strong>PubMed</strong> to gather supporting literature:</p>
            
            <ul>
                <li>Search for gene knockout/deletion studies</li>
                <li>Extract reported phenotypes</li>
                <li>Assess viability data</li>
                <li>Count relevant publications</li>
            </ul>
            
            <p>When enabled, the <strong>RAG (Retrieval-Augmented Generation)</strong> system uses 
            natural language processing to predict knockout phenotypes based on the literature corpus.</p>
        """
    },
    {
        "title": "Step 5: Measured Knockout Evidence",
        "icon": "fa-vial",
        "content": """
            <p>Every gene is looked up in the published knockout data (mouse, yeast, zebrafish, fly and worm knockouts, human cell-line
            screens, tolerance of loss-of-function variants, tissue expression and paralogs). See
            <a href="#knockout_evidence">Measured knockout evidence</a>. Genes above the pleiotropy cutoff are not
            dropped silently: they are listed as "not shown" together with their measured result.</p>
        """
    },
    {
        "title": "Step 6: Safety Assessment",
        "icon": "fa-shield-alt",
        "content": """
            <p>The final step turns the evidence into a verdict and advice:</p>

            <ul>
                <li>The measured result for your knockout context decides the level (lethal: AVOID; reduced survival or
                    lethal in some lines: HIGH_CONCERN; viable: SAFE, or CAUTION when the gene has many annotated roles,
                    a shortened lifespan or infertility has been reported)</li>
                <li>Where nothing was measured the verdict is never better than CAUTION and is marked "Not verified"</li>
                <li>Specific advice follows from the finding: a conditional allele for a lethal gene, a double knockout
                    where a close paralog may compensate, a tissue-specific knockout where expression is restricted</li>
            </ul>

            <p>Safety levels range from SAFE (safe to proceed) to AVOID (a complete knockout is lethal or kills the cells).</p>
        """
    },
    {
        "title": "Output Generation",
        "icon": "fa-file-export",
        "content": """
            <p>Results are provided in multiple formats:</p>
            
            <ul>
                <li><strong>HTML Report:</strong> Interactive, publication-ready summary</li>
                <li><strong>CSV Tables:</strong> Gene-level data for spreadsheets</li>
                <li><strong>JSON:</strong> Complete data for programmatic access</li>
            </ul>
            
            <p>All results include detailed metadata, quality scores, and safety recommendations 
            to support experimental design decisions.</p>
        """
    }
]


FAQ_ITEMS = [
    {
        "question": "What is the difference between pleiotropy score and specificity score?",
        "answer": "Pleiotropy score measures how many processes a gene is involved in (0=specific, high=broad). Specificity score is the inverse on a 0-1 scale (1 minus pleiotropy divided by 10), so higher values indicate more specific genes. Both convey the same information but in opposite directions."
    },
    {
        "question": "How accurate is the phenotype prediction?",
        "answer": "Not very, which is why it is only a fallback. On a random sample of 60 mouse genes with a known knockout outcome it recognised 7 of the 30 lethal genes, wrongly called 4 of the 30 viable genes lethal, and gave no answer for two thirds. Genes with a measured knockout result are never predicted. Always validate predictions experimentally."
    },
    {
        "question": "How do I know the lethal / viable calls are right?",
        "answer": "They are the published measurements, not guesses: the MGI literature curation and the IMPC knockout screen for mouse, SGD for yeast, ZFIN for zebrafish, FlyBase for fly, WormBase for worm, DepMap for human cell lines. We checked them against the original papers of 24 well-known knockouts in mouse, zebrafish, fly and worm (all 24 agree, see the Validation page), and the two mouse sources agree for 92% of the 7,500 genes that both cover. Each gene lists the papers (PubMed links) behind its result."
    },
    {
        "question": "Why is a gene fine in human cells but marked AVOID in the mouse?",
        "answer": "Because the two measure different things. A gene needed for embryonic development (such as TDG or POLB) kills the mouse embryo, yet cultured cells, which do not have to develop, often manage without it. Choose 'What will you knock out?' to make the verdict follow your system; both results are always shown."
    },
    {
        "question": "What does 'not shown' mean?",
        "answer": "Every gene of the GO term is assessed. The report shows the safest 'Genes to report' genes; the rest, and the genes above your pleiotropy cutoff, are listed under 'Genes assessed but not shown' with their measured knockout result, so a gene is never hidden without a trace."
    },
    {
        "question": "Why does a gene say 'viable' but still carry a warning?",
        "answer": "Viable knockouts can still have a shortened lifespan, be infertile, or show phenotypes in many organs; the report lists these. If some knockout lines of the gene were lethal (a different strain or allele) the gene is rated at least HIGH_CONCERN even when most lines were viable."
    },
    {
        "question": "What if my gene has a high pleiotropy score?",
        "answer": "High pleiotropy doesn't necessarily mean you shouldn't target the gene, but be prepared for complex phenotypes. Consider: 1) Using heterozygous or conditional knockouts, 2) Including pathway information in your interpretation, 3) Validating with an independent approach."
    },
    {
        "question": "How long does an analysis take?",
        "answer": "Typical runtime is 2-5 minutes for 5-10 genes. Factors affecting speed: number of genes, phenotype prediction (adds ~1 min/gene), and database response times."
    }
]
