from fpdf import FPDF
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import os


def create_flowchart_image(path='bp_count_flowchart.png'):
    """Create the BP_count calculation flowchart as a PNG image."""
    width, height = 720, 950
    img = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(img)

    # Try to load a decent font, fall back to default
    try:
        font_title = ImageFont.truetype("arial.ttf", 26)
        font_box = ImageFont.truetype("arial.ttf", 22)
        font_small = ImageFont.truetype("arial.ttf", 20)
        font_formula = ImageFont.truetype("arial.ttf", 24)
    except Exception:
        font_title = ImageFont.load_default()
        font_box = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_formula = ImageFont.load_default()

    # Colors
    box_fill = (230, 242, 255)
    box_border = (33, 64, 95)
    text_color = (30, 30, 30)
    arrow_color = (80, 80, 80)

    def draw_rounded_rect(draw, xy, fill, outline, width=2, radius=10):
        x1, y1, x2, y2 = xy
        draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)

    def text_size(text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def draw_centered_text(text, font, y, color=text_color):
        w, h = text_size(text, font)
        x = (width - w) // 2
        draw.text((x, y), text, font=font, fill=color)
        return y + h

    def draw_box(text_lines, y, box_height=70):
        box_width = 280
        x1 = (width - box_width) // 2
        x2 = x1 + box_width
        y1 = y
        y2 = y + box_height
        draw_rounded_rect(draw, (x1, y1, x2, y2), box_fill, box_border, width=2, radius=12)

        # Draw each line centered
        total_h = len(text_lines) * 26
        start_y = y + (box_height - total_h) // 2 + 2
        for i, line in enumerate(text_lines):
            w, h = text_size(line, font_box)
            lx = (width - w) // 2
            draw.text((lx, start_y + i * 26), line, font=font_box, fill=text_color)
        return y2

    def draw_arrow(y1, y2):
        x = width // 2
        draw.line([(x, y1), (x, y2)], fill=arrow_color, width=2)
        # Arrowhead
        draw.polygon([(x - 6, y2 - 10), (x + 6, y2 - 10), (x, y2)], fill=arrow_color)

    # Starting y position
    y = 30

    # Title
    y = draw_centered_text("BP Count Calculation Flowchart", font_title, y)
    y += 30

    # Top label
    y = draw_centered_text("Gene symbol + organism", font_small, y)
    y += 15
    draw_arrow(y, y + 25)
    y += 35

    # Two boxes side by side
    box_w = 260
    box_h = 80
    gap = 60
    total_w = 2 * box_w + gap
    start_x = (width - total_w) // 2

    # QuickGO box
    draw_rounded_rect(draw, (start_x, y, start_x + box_w, y + box_h), box_fill, box_border, width=2, radius=12)
    draw.text((start_x + 50, y + 22), "QuickGO", font=font_box, fill=text_color)
    draw.text((start_x + 45, y + 48), "BP terms", font=font_box, fill=text_color)

    # UniProt box
    ux = start_x + box_w + gap
    draw_rounded_rect(draw, (ux, y, ux + box_w, y + box_h), box_fill, box_border, width=2, radius=12)
    draw.text((ux + 70, y + 22), "UniProt", font=font_box, fill=text_color)
    draw.text((ux + 65, y + 48), "BP terms", font=font_box, fill=text_color)

    # Arrows from boxes down to merge point
    merge_y = y + box_h + 40
    draw.line([(start_x + box_w // 2, y + box_h), (start_x + box_w // 2, merge_y)], fill=arrow_color, width=2)
    draw.line([(ux + box_w // 2, y + box_h), (ux + box_w // 2, merge_y)], fill=arrow_color, width=2)
    # Horizontal connector
    draw.line([(start_x + box_w // 2, merge_y), (ux + box_w // 2, merge_y)], fill=arrow_color, width=2)
    # Down arrow
    draw.line([(width // 2, merge_y), (width // 2, merge_y + 25)], fill=arrow_color, width=2)
    draw.polygon([(width // 2 - 6, merge_y + 25 - 10), (width // 2 + 6, merge_y + 25 - 10), (width // 2, merge_y + 25)], fill=arrow_color)

    y = merge_y + 35

    # Merge label
    y = draw_centered_text("merge by GO ID", font_small, y)
    y = draw_centered_text("keep stronger evidence", font_small, y)
    y += 10
    draw_arrow(y, y + 25)
    y += 35

    # combined_bp_terms box
    y = draw_box(["combined_bp_terms"], y, box_height=60)
    y += 10
    draw_arrow(y, y + 25)
    y += 35

    # Evidence filter label
    y = draw_centered_text("apply evidence filter", font_small, y)
    y = draw_centered_text("(experimental / computational / all)", font_small, y)
    y += 10
    draw_arrow(y, y + 25)
    y += 35

    # effective_bp_count box
    y = draw_box(["effective_bp_count"], y, box_height=60)
    y += 10
    draw_arrow(y, y + 25)
    y += 35

    # Formula
    formula_lines = [
        "pleiotropy_score =",
        "10 x (1 - e^(-0.3 x (effective_bp_count - 1)))"
    ]
    y = draw_centered_text(formula_lines[0], font_formula, y)
    y = draw_centered_text(formula_lines[1], font_formula, y)

    img.save(path)
    return path


class PDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 12)
        self.set_text_color(40, 40, 40)
        self.cell(0, 10, 'K-Sites: Databases Compatible with BP Count Merging', new_x="LMARGIN", new_y="NEXT", align='C')
        self.ln(2)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', new_x="RIGHT", new_y="TOP", align='C')

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(33, 64, 95)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT", align='L')
        self.ln(1)

    def body_text(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def bullet(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 6, chr(149) + ' ' + text)
        self.ln(1)

    def db_title(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(33, 64, 95)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def db_body(self, text):
        self.set_font('Helvetica', '', 10)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 6, text)
        self.ln(1)

    def db_api(self, text):
        self.set_font('Helvetica', 'I', 9)
        self.set_text_color(80, 80, 80)
        self.multi_cell(0, 5, text)
        self.ln(2)


# Generate flowchart image
flowchart_path = create_flowchart_image()

pdf = PDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

# Title block
pdf.set_font('Helvetica', 'B', 16)
pdf.set_text_color(33, 64, 95)
pdf.cell(0, 10, 'Recommended Databases for Merging into K-Sites BP Count', new_x="LMARGIN", new_y="NEXT", align='C')
pdf.set_font('Helvetica', '', 10)
pdf.set_text_color(80, 80, 80)
pdf.cell(0, 8, f'Prepared: {datetime.now().strftime("%Y-%m-%d")}', new_x="LMARGIN", new_y="NEXT", align='C')
pdf.ln(5)

# Insert flowchart image
pdf.image(flowchart_path, x=25, w=160)
pdf.ln(5)

# Rationale
pdf.section_title('Rationale')
pdf.body_text(
    'The BP_count in K-Sites measures how many distinct Biological Process roles a gene has. '
    'To keep this count biologically meaningful, every item merged into it must represent a '
    'comparable Biological Process concept.'
)

pdf.section_title('Why QuickGO and UniProt merge cleanly')
pdf.bullet('Both annotate genes using Gene Ontology (GO) Biological Process terms.')
pdf.bullet('They share the same IDs (e.g., GO:0006281) and term names (e.g., DNA repair).')
pdf.bullet('They use the same evidence-code system (IDA, IMP, IEA, etc.).')
pdf.bullet('K-Sites resolves conflicts by keeping the strongest evidence type for each GO term.')
pdf.ln(3)

pdf.section_title('Why KEGG, Reactome, and similar databases do not merge cleanly')
pdf.bullet('KEGG uses pathway IDs (e.g., hsa03440), not GO terms.')
pdf.bullet('KEGG mixes biological mechanisms (Homologous recombination) with disease categories (Breast cancer).')
pdf.bullet('Reactome uses reaction-based pathway IDs (e.g., R-HSA-73894) and requires GO mapping.')
pdf.bullet('Neither uses GO evidence codes, breaking the evidence-filter logic.')
pdf.bullet('Merging them would count incomparable items: processes, pathways, and diseases as if they were the same unit of biological breadth.')
pdf.ln(3)

pdf.section_title('The comparability test')
pdf.body_text(
    'Before adding any new database to BP_count, each returned item should pass this test: '
    'Is it a Biological Process? Is it at a similar specificity level as GO BP terms? '
    'Does it use a shared ID system or a direct GO mapping? If the answer is no, keep it as a separate metric.'
)

pdf.add_page()

# Recommendations
pdf.section_title('Recommended databases for clean merging')
pdf.body_text('These databases return standard GO Biological Process terms and can be merged into BP_count without distorting its meaning.')

pdf.section_title('Tier 1: General-purpose candidates')

pdf.db_title('1. Ensembl')
pdf.db_body(
    'Provides gene-level GO annotations with evidence codes. Broad species coverage, stable REST API, '
    'and BioMart access. Best single general-purpose addition.'
)
pdf.db_api('API example: rest.ensembl.org/xrefs/name/human/BRCA1?external_db=GO;object_type=gene')

pdf.db_title('2. NCBI Gene')
pdf.db_body(
    'Authoritative gene-centric GO annotations covering all NCBI-supported species. '
    'Useful as a cross-check against QuickGO and UniProt.'
)
pdf.db_api('API example: eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gene&id=672&retmode=json')

pdf.db_title('3. MyGene.info')
pdf.db_body(
    'Fast aggregator that returns structured GO BP/MF/CC annotations from multiple primary sources. '
    'Simplest API to implement.'
)
pdf.db_api('API example: mygene.info/v3/query?q=BRCA1&fields=go')
pdf.ln(2)

pdf.section_title('Tier 2: Species-specific model organism databases')
pdf.body_text('Each uses GO terms with evidence codes. Most valuable when the target organism is the database\'s primary species.')
pdf.bullet('MGI - Mouse')
pdf.bullet('FlyBase - Drosophila')
pdf.bullet('WormBase - C. elegans')
pdf.bullet('ZFIN - Zebrafish')
pdf.bullet('SGD - Yeast')
pdf.bullet('RGD - Rat')
pdf.bullet('TAIR - Arabidopsis')
pdf.bullet('Xenbase - Xenopus')
pdf.ln(4)

pdf.section_title('Tier 3: Official but largely redundant')
pdf.bullet('AmiGO / GOlr - Official GO Consortium data. QuickGO already serves the same underlying annotations, so added coverage is minimal.')
pdf.bullet('Alliance of Genome Resources - Aggregates GO annotations across model organisms. Useful for cross-species work.')
pdf.ln(4)

pdf.add_page()

# Databases to avoid
pdf.section_title('Databases to keep separate from BP_count')
pdf.body_text('These databases provide valuable context but should not be merged into BP_count because they do not return GO Biological Process terms.')

avoid = [
    ('KEGG', 'Pathway IDs, not GO terms; mixes biological mechanisms with disease categories'),
    ('Reactome', 'Reaction-based pathway IDs; requires GO mapping'),
    ('STRING', 'Protein-protein interactions, not biological processes'),
    ('BioGPS / GeneAtlas', 'Gene expression data'),
    ('InterPro', 'Protein domains and families'),
    ('MSigDB', 'Curated gene sets, not GO ontology'),
    ('WikiPathways', 'Pathway diagrams'),
    ('DisGeNET / OMIM', 'Disease and phenotype associations'),
]

pdf.set_font('Helvetica', 'B', 10)
pdf.set_fill_color(240, 240, 240)
pdf.cell(50, 8, 'Database', 1, new_x="RIGHT", new_y="TOP", align='L', fill=True)
pdf.cell(0, 8, 'Reason to keep separate', 1, new_x="LMARGIN", new_y="NEXT", align='L', fill=True)
pdf.set_font('Helvetica', '', 10)
for name, reason in avoid:
    pdf.cell(50, 7, name, 1, new_x="RIGHT", new_y="TOP", align='L')
    pdf.cell(0, 7, reason, 1, new_x="LMARGIN", new_y="NEXT", align='L')
pdf.ln(5)

# Summary
pdf.section_title('Summary recommendation')
pdf.body_text(
    'Keep BP_count strictly based on GO Biological Process annotations. '
    'Add Ensembl as the next primary GO source alongside QuickGO and UniProt. '
    'Use KEGG, Reactome, and other pathway or disease databases as separate metrics, not as inputs to BP_count.'
)

# Final summary table
pdf.section_title('Merge compatibility cheat sheet')

pdf.set_font('Helvetica', 'B', 10)
pdf.set_fill_color(230, 240, 230)
pdf.cell(80, 8, 'Merge cleanly into BP_count', 1, new_x="RIGHT", new_y="TOP", align='L', fill=True)
pdf.cell(0, 8, 'Keep separate', 1, new_x="LMARGIN", new_y="NEXT", align='L', fill=True)
pdf.set_font('Helvetica', '', 10)

merge_yes = 'Ensembl, NCBI Gene, MyGene.info, MODs, AmiGO/GOlr, Alliance'
merge_no = 'KEGG, Reactome, STRING, BioGPS, InterPro, MSigDB, WikiPathways, DisGeNET, OMIM'

start_y = pdf.get_y()
pdf.multi_cell(80, 6, merge_yes, 1, align='L')
height = pdf.get_y() - start_y
pdf.set_xy(90, start_y)
pdf.multi_cell(0, 6, merge_no, 1, align='L')

output_path = 'k_sites_database_recommendations.pdf'
pdf.output(output_path)
print(f'PDF generated: {output_path}')
