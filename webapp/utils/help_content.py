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
                    <tr><td class="text-warning"><strong>5-10</strong></td><td>Broadly involved - use with caution</td></tr>
                    <tr><td class="text-danger"><strong>>10</strong></td><td>Highly pleiotropic - may cause unintended effects</td></tr>
                </table>
            </div>
            
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
            
            <h6>Risk Factors Considered:</h6>
            <ul>
                <li>Pleiotropy score (high = higher risk)</li>
                <li>Predicted phenotype severity (lethal = critical)</li>
                <li>Literature evidence of essentiality</li>
                <li>Cross-species conservation</li>
            </ul>
        """,
        "reference": "K-Sites integrated safety assessment algorithm"
    },
    
    "phenotype_prediction": {
        "title": "RAG Phenotype Prediction",
        "icon": "fa-brain",
        "short_description": "AI-powered prediction of knockout phenotypes from literature",
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
            
            <h6>Limitations:</h6>
            <p>Prediction quality depends on literature availability. Well-studied genes have more 
            accurate predictions than poorly characterized genes.</p>
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
        "title": "Step 5: Safety Assessment",
        "icon": "fa-shield-alt",
        "content": """
            <p>The final step integrates all analyses to provide safety recommendations:</p>
            
            <ul>
                <li>Combine pleiotropy, phenotype, conservation and literature data</li>
                <li>Assess risk of essential gene knockout</li>
                <li>Generate specific experimental recommendations</li>
                <li>Flag genes requiring additional validation</li>
            </ul>
            
            <p>Safety levels range from SAFE (safe to proceed) to AVOID (may be lethal/essential).</p>
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
        "answer": "Phenotype prediction accuracy depends on literature availability for the gene. Well-studied genes (like TP53) have highly accurate predictions, while poorly characterized genes may return 'UNKNOWN'. Always validate predictions experimentally."
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
