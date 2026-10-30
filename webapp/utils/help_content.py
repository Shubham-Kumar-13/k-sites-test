"""
Help content and documentation for K-Sites analytical terms
"""

ANALYTICAL_TERMS = {
    "pleiotropy_score": {
        "title": "Pleiotropy Score",
        "icon": "fa-project-diagram",
        "short_description": "How many biological processes a gene is annotated to (a hint about how broad its effects may be)",
        "detailed_explanation": """
            <p>The <strong>Pleiotropy Score</strong> counts how many different biological processes a gene is annotated
            to. The more roles a gene has, the broader the effects of removing it may be.</p>

            <h6>How it's calculated:</h6>
            <ul>
                <li>Counts the Biological Process GO terms of the gene (with the evidence type you chose).</li>
                <li>Score = 10 &times; (1 &minus; e<sup>&minus;0.3 &times; (n &minus; 1)</sup>), where n is the total number of BP terms found for the gene (the <em>n &minus; 1</em> excludes the target GO term itself):
                    1 term gives 0, 2 terms 2.6, 3 terms 4.5, 5 terms 7.0, 8 terms 8.8, and 11 or more terms give 10.</li>
                <li>The number of KEGG pathways is shown next to the score but is not part of it.</li>
            </ul>

            <h6>Score Range:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr><td class="text-success"><strong>0-2</strong></td><td>Very few annotated roles</td></tr>
                    <tr><td class="text-info"><strong>2-5</strong></td><td>A few annotated roles</td></tr>
                    <tr><td class="text-warning"><strong>5-8</strong></td><td>Many annotated roles: expect broader phenotypes</td></tr>
                    <tr><td class="text-danger"><strong>8-10</strong></td><td>Very many annotated roles</td></tr>
                </table>
            </div>

            <h6>Max pleiotropy (cutoff):</h6>
            <p>The score is always on a 0-10 scale. The <strong>max pleiotropy</strong> setting is a cutoff on that
            score: genes scoring above it are left out of the ranking (they are listed as "not shown" with their
            measured result). 0 keeps only the most specific genes, 10 keeps everything.</p>

            <h6>How far it can be trusted:</h6>
            <p>We compared the score with what is measured when the gene is knocked out in the mouse (13,733 genes, see the
            <a href="/validation">Validation page</a>). Genes with a higher score do affect more organ systems and are more often
            lethal (14% lethal in the lowest band, 37% in the highest), but the link is modest: the rank correlation with the
            number of organ systems affected is 0.34, and the area under the ROC curve for telling lethal from viable is 0.61
            (0.5 is a coin flip). Heavily studied genes simply have more annotations. Use the score as a hint about broad
            effects; the measured knockout result matters more.</p>
        """,
        "reference": "GO Biological Process annotations; checked against MGI and IMPC knockouts (Validation page)"
    },

    "specificity_score": {
        "title": "Specificity Score",
        "icon": "fa-bullseye",
        "short_description": "The inverse of pleiotropy on a 0 to 1 scale - higher is more specific",
        "detailed_explanation": """
            <p>The <strong>Specificity Score</strong> is <code>1 &minus; pleiotropy_score / 10</code>, so it runs from
            0 (very many annotated roles) to 1 (a single annotated process). A pleiotropy score of 2.6 gives 0.74.</p>

            <h6>Interpretation:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr><td class="text-success"><strong>0.8-1.0</strong></td><td>Few annotated roles</td></tr>
                    <tr><td class="text-info"><strong>0.5-0.8</strong></td><td>A few annotated roles</td></tr>
                    <tr><td class="text-warning"><strong>0.2-0.5</strong></td><td>Many annotated roles</td></tr>
                    <tr><td class="text-danger"><strong>0-0.2</strong></td><td>Very many annotated roles</td></tr>
                </table>
            </div>

            <h6>Usage:</h6>
            <p>It carries no information beyond the pleiotropy score; it is used because the composite score rewards genes
            with fewer annotated roles. Whether a knockout is safe is decided by the measured knockout evidence, not by this score.</p>
        """,
        "reference": "Derived from the pleiotropy score"
    },

    "composite_score": {
        "title": "Composite Score",
        "icon": "fa-star",
        "short_description": "Weighted combination of specificity, evidence quality, literature support and conservation",
        "detailed_explanation": """
            <p>The <strong>Composite Score</strong> combines four measures into one number between 0 and 1. It orders the
            genes that have the same safety level; the safety level itself comes from the
            <a href="#knockout_evidence">measured knockout evidence</a>.</p>

            <h6>Formula:</h6>
            <div class="alert alert-light">
                <code>Composite = 0.40 &times; Specificity + 0.25 &times; Evidence Quality + 0.20 &times; Literature + 0.15 &times; Conservation</code>
            </div>

            <h6>Components (each from 0 to 1):</h6>
            <ul>
                <li><strong>Specificity (40%):</strong> 1 &minus; pleiotropy score / 10.</li>
                <li><strong>Evidence Quality (25%):</strong> the share of the gene's annotations that rest on experiments (weight 1.0),
                    computational analysis (0.6) or electronic annotation (0.3).</li>
                <li><strong>Literature (20%):</strong> the PubMed articles that NCBI Gene links to the gene, on a log scale:
                    1 article or none gives 0, 10 give 0.33, 100 give 0.67, 1,000 or more give 1.</li>
                <li><strong>Conservation (15%):</strong> the share of five model species (human, mouse, rat, fly, worm) that have the
                    gene or an ortholog of it (see Conservation).</li>
            </ul>

            <h6>Range:</h6>
            <p>0 to 1; higher means a better candidate by these measures. The weights are a design choice, not fitted to knockout
            outcomes.</p>
        """,
        "reference": "Weighted scoring of annotation, literature and orthology data"
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
                <li>Without any measurement the verdict follows an <strong>estimate</strong> of lethality made from the
                    measurements of the gene's human ortholog (cell lines, tolerance of loss-of-function variants, expression),
                    and it is <strong>never better than CAUTION</strong>. The report says "Estimated from data". Where even
                    that is impossible it says "Not verified".</li>
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
                    <tr><td><strong>Estimated from data (not measured)</strong></td><td>no knockout was measured; the chance that it is lethal in mice is estimated from the human ortholog's cell-line, population and expression data (a model tested on genes with known outcomes: see the <a href="/validation">Validation page</a>)</td></tr>
                    <tr><td><strong>Predicted from the literature</strong></td><td>nothing was measured and no estimate exists; a keyword model read abstracts (experimental, see below)</td></tr>
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
        "short_description": "A literature-based guess for genes with no measured knockout data",
        "detailed_explanation": """
            <p><strong>Retrieval-Augmented Generation (RAG)</strong> phenotype prediction reads PubMed abstracts
            and guesses the likely knockout phenotype for genes that have no measured result and no cross-species
            estimate. It is switched off by default.</p>

            <h6>When to use it:</h6>
            <ul>
                <li><strong>Turn it on</strong> for short lists (a few dozen genes), well-studied organisms,
                    and when you can wait a few minutes. It gives at least a literature hint for genes that
                    otherwise have no data.</li>
                <li><strong>Leave it off</strong> for human and mouse (measured data already cover most genes),
                    for organisms like zebrafish, Xenopus, fly, worm or rat where thousands of genes have no data,
                    for lists above ~100 genes, and when you want the result quickly.</li>
            </ul>

            <h6>Optional hosted language-model API key:</h6>
            <p>You can paste an API key for one of the supported providers to let a larger language model read the
            abstracts. The key is used only in your browser and is never sent to the K-Sites server. If the key is
            blank or the API fails, the analysis falls back automatically to the free browser model
            (MiniLM + keyword patterns).</p>

            <p><strong>Supported providers:</strong></p>
            <ul>
                <li><strong>Kimi (Moonshot)</strong> — default; strong context understanding.</li>
                <li><strong>OpenAI</strong> — <code>gpt-4o-mini</code> or other chat models.</li>
                <li><strong>Anthropic</strong> — Claude 3.5 Sonnet via the Messages API.</li>
                <li><strong>Qwen (Alibaba)</strong> — DashScope compatible endpoint.</li>
                <li><strong>DeepSeek</strong> — <code>deepseek-chat</code>.</li>
                <li><strong>Grok (xAI)</strong> — <code>grok-2-latest</code>.</li>
            </ul>

            <p><strong>Why it helps:</strong> The default browser model matches keywords and counts how often words
            like “lethal” or “viable” appear. It works for clear cases but can be misled by negation
            (for example, “the knockout was <em>not</em> lethal”), by sentences about a different gene in the same
            paper, or by conflicting reports. A hosted language model reads the abstracts as a whole, understands
            context, resolves contradictions, and usually returns a more reliable severity call.</p>

            <p><strong>How to get a key:</strong></p>
            <ol>
                <li>Choose a provider in the “Language model provider” drop-down on the analysis page.</li>
                <li>Create an account with that provider and generate an API key:
                    <ul>
                        <li><strong>Kimi:</strong> <a href="https://platform.moonshot.ai" target="_blank">platform.moonshot.ai</a>
                            → API keys (starts with <code>sk-</code>).</li>
                        <li><strong>OpenAI:</strong> <a href="https://platform.openai.com/api-keys" target="_blank">platform.openai.com/api-keys</a>
                            (starts with <code>sk-proj-</code> or <code>sk-</code>).</li>
                        <li><strong>Anthropic:</strong> <a href="https://console.anthropic.com/settings/keys" target="_blank">console.anthropic.com/settings/keys</a>
                            (starts with <code>sk-ant-</code>).</li>
                        <li><strong>Qwen:</strong> <a href="https://dashscope.console.aliyun.com/apiKey" target="_blank">dashscope.console.aliyun.com/apiKey</a>
                            (starts with <code>sk-</code>).</li>
                        <li><strong>DeepSeek:</strong> <a href="https://platform.deepseek.com/api_keys" target="_blank">platform.deepseek.com/api_keys</a>
                            (starts with <code>sk-</code>).</li>
                        <li><strong>Grok:</strong> <a href="https://console.x.ai" target="_blank">console.x.ai</a>
                            → API keys (starts with <code>xai-</code>).</li>
                    </ul>
                </li>
                <li>Copy the key and paste it into the “API key (optional)” field after enabling “RAG Phenotype Prediction”.</li>
                <li>The key is stored only in your browser for that analysis; you will need to paste it again
                    on a different device or after clearing browser data.</li>
            </ol>

            <p><strong>Cost:</strong> The provider bills you directly for the tokens used. A typical K-Sites run with
            ~25 unmeasured genes usually costs a few cents (USD), but this depends on the model, provider rates and
            abstract lengths. Check the provider's pricing page for current rates.</p>

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

            <h6>Limitations:</h6>
            <p>It is only used for genes without a <a href="#knockout_evidence">measured knockout result</a> and
            without an estimate, and it is capped at 25 genes per job. We tested the free model on a random sample
            of 60 mouse genes with known outcomes: it recognised 7 of 30 lethal genes, wrongly called 4 of 30 viable
            genes lethal, and gave no answer for two thirds (see the <a href="/validation">Validation page</a>).
            Treat any prediction as a hint to read the papers, not as a result.</p>
        """,
        "reference": "RAG-based NLP pipeline using PubMed; optional hosted LLM fallback (Kimi, OpenAI, Anthropic, Qwen, DeepSeek, Grok)"
    },
    
    "conservation_score": {
        "title": "Cross-Species Conservation",
        "icon": "fa-globe",
        "short_description": "In how many of five model species the gene, or an ortholog of it, exists",
        "detailed_explanation": """
            <p>The <strong>Conservation Score</strong> is the share of five model species (human, mouse, rat, fruit fly and
            worm) that carry the gene or an ortholog of it. The organism you analyse counts for itself.</p>

            <h6>How it's calculated:</h6>
            <ul>
                <li>The orthologs come from the Alliance of Genome Resources. A call counts when at least three of its
                    algorithms agree, or two agree and it is the best pair in both directions.</li>
                <li>Score = species with the gene or an ortholog / 5, so it takes the values 0, 0.2, 0.4, 0.6, 0.8 and 1.</li>
                <li>Orthologs are matched by identifier, not by name: the fly counterpart of PCNA is called mus209, and a gene
                    with the same name in another species is not necessarily an ortholog.</li>
            </ul>

            <h6>Interpretation:</h6>
            <div class="table-responsive">
                <table class="table table-sm">
                    <tr><td class="text-info"><strong>0-0.2</strong></td><td>Found in one species only: possibly species-specific</td></tr>
                    <tr><td class="text-success"><strong>0.4-0.8</strong></td><td>Moderately conserved</td></tr>
                    <tr><td class="text-warning"><strong>1.0</strong></td><td>In all five species: an old, widely kept gene</td></tr>
                </table>
            </div>

            <h6>Usage:</h6>
            <p>Genes kept in all five species are more often needed for basic functions, so the report notes it. It does not
            decide the verdict: the measured knockout result does. For organisms without orthology data (plants, for example)
            the conservation is searched for by gene name instead, which is less precise.</p>
        """,
        "reference": "Alliance of Genome Resources orthologs (Validation page for the checks of the other scores)"
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
            <p>The <strong>literature score</strong> counts the PubMed articles that NCBI Gene links to the gene
            (the gene2pubmed list), not a text search of its name, so a gene symbol that is also an ordinary word
            is not confused with the gene. The count is shown with each gene and enters the composite score.</p>

            <p>When enabled, the experimental <strong>RAG (Retrieval-Augmented Generation)</strong> predictor reads
            abstracts to guess knockout phenotypes, but only for genes that have neither a measured knockout result nor
            a lethality estimate.</p>
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
