"""
K-Sites Web Application - Enhanced Version
Flask backend for the K-Sites safe gene selection tool
"""

import os
import sys
import hmac
import json
import uuid
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional

from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session, flash
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from functools import wraps

# Add parent directory to path for K-Sites imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import K-Sites modules
from k_sites.data_retrieval.organism_resolver import resolve_organism, search_organisms
from k_sites.data_retrieval.go_gene_mapper import get_genes_for_go_term, search_go_terms
from k_sites.workflow.pipeline import run_k_sites_pipeline
from k_sites.reporting.report_generator import generate_html_report
from k_sites.reporting.csv_export import generate_comprehensive_csv_report

# Import webapp utilities
from utils.hierarchical_data import (
    search_organisms_by_kingdom, search_go_terms_by_category,
    get_kingdoms, get_go_categories
)
from utils.help_content import ANALYTICAL_TERMS, METHODOLOGY_SECTIONS, FAQ_ITEMS

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app configuration
app = Flask(__name__, template_folder='templates', static_folder='static')

# Hosted mode: when KSITES_ACCESS_TOKEN is set, this server is an API-only backend for the
# GitHub Pages front-end. Every API call must carry the lab access token, and only the
# listed origins may call it from a browser.
ACCESS_TOKEN = os.environ.get('KSITES_ACCESS_TOKEN', '').strip()
HOSTED_MODE = bool(ACCESS_TOKEN)
ALLOWED_ORIGINS = [o.strip().rstrip('/') for o in os.environ.get('KSITES_ALLOWED_ORIGINS', '').split(',') if o.strip()]
MAX_PARALLEL_JOBS = max(1, int(os.environ.get('KSITES_MAX_PARALLEL_JOBS', '2')))

if HOSTED_MODE:
    CORS(app,
         origins=ALLOWED_ORIGINS,
         methods=['GET', 'POST', 'OPTIONS'],
         allow_headers=['Content-Type', 'X-KSites-Token', 'X-KSites-User-Name', 'X-KSites-User-Email'],
         expose_headers=['Content-Disposition'])
    if not ALLOWED_ORIGINS:
        logger.warning("KSITES_ACCESS_TOKEN is set but KSITES_ALLOWED_ORIGINS is empty: "
                       "browsers will be blocked. Set it to your GitHub Pages address.")
else:
    CORS(app)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Database configuration
# KSITES_DATA_DIR lets a deployment keep the database and results on a writable disk
RESULTS_DIR = Path(os.environ.get('KSITES_DATA_DIR') or Path(__file__).parent / 'results')
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{RESULTS_DIR}/ksites_jobs.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'ksites@example.com')

# Initialize extensions
db = SQLAlchemy(app)
mail = Mail(app)

# Default configuration
os.environ.setdefault('K_SITES_NCBI_EMAIL', os.environ.get('MAIL_USERNAME', 'user@example.com'))

# Preload organisms in background for faster response
def _preload_organisms():
    """Preload organisms from KEGG in background."""
    try:
        from utils.hierarchical_data import fetch_kegg_organisms
        logger.info("Preloading organisms from KEGG...")
        fetch_kegg_organisms()
        logger.info("Organisms preloaded successfully")
    except Exception as e:
        logger.warning(f"Could not preload organisms: {e}")

# Start preload in background thread
preload_thread = threading.Thread(target=_preload_organisms, daemon=True)
preload_thread.start()


# ============================================================================
# Database Models
# ============================================================================

class User(db.Model):
    """Database model for users"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True)
    institute = db.Column(db.String(300), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'institute': self.institute,
            'country': self.country,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


class AnalysisJob(db.Model):
    """Database model for analysis jobs"""
    __tablename__ = 'analysis_jobs'
    
    id = db.Column(db.String(36), primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status = db.Column(db.String(20), default='pending')
    current_step = db.Column(db.String(100))
    progress_percent = db.Column(db.Integer, default=0)
    estimated_completion = db.Column(db.DateTime)
    
    # User info (linked to User model)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    user_email = db.Column(db.String(200))
    
    # Input parameters
    organism = db.Column(db.String(200), nullable=False)
    taxid = db.Column(db.String(20))
    go_term = db.Column(db.String(20), nullable=False)
    go_term_name = db.Column(db.String(500))
    max_genes = db.Column(db.Integer, default=10)
    max_pleiotropy = db.Column(db.Integer, default=5)
    evidence_filter = db.Column(db.String(20), default='experimental')
    predict_phenotypes = db.Column(db.Boolean, default=False)
    selected_databases = db.Column(db.Text)
    
    # Results
    total_genes_found = db.Column(db.Integer)
    genes_processed = db.Column(db.Integer)
    results_path = db.Column(db.String(500))
    error_message = db.Column(db.Text)
    
    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'status': self.status,
            'current_step': self.current_step,
            'progress_percent': self.progress_percent,
            'estimated_completion': self.estimated_completion.isoformat() if self.estimated_completion else None,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'organism': self.organism,
            'taxid': self.taxid,
            'go_term': self.go_term,
            'go_term_name': self.go_term_name,
            'max_genes': self.max_genes,
            'max_pleiotropy': self.max_pleiotropy,
            'evidence_filter': self.evidence_filter,
            'predict_phenotypes': self.predict_phenotypes,
            'selected_databases': json.loads(self.selected_databases) if self.selected_databases else [],
            'total_genes_found': self.total_genes_found,
            'genes_processed': self.genes_processed,
            'results_path': self.results_path,
            'error_message': self.error_message
        }


# Initialize database
with app.app_context():
    db.create_all()
    try:
        interrupted = AnalysisJob.query.filter(AnalysisJob.status.in_(['pending', 'running'])).all()
        for stale in interrupted:
            stale.status = 'failed'
            stale.current_step = 'Failed'
            stale.error_message = 'The server restarted while this job was running. Please submit it again.'
        if interrupted:
            db.session.commit()
    except Exception as startup_error:  # a fresh database may not have every column yet
        db.session.rollback()
        logger.warning(f"Could not clean up interrupted jobs: {startup_error}")


# ============================================================================
# Email Functions
# ============================================================================

def send_job_notification(job: AnalysisJob, notification_type: str):
    """Send email notification to user"""
    if not job.user_email or not app.config['MAIL_USERNAME']:
        return
    
    try:
        if notification_type == 'submitted':
            subject = f"K-Sites Analysis Started - Job {job.id[:8]}"
            body = f"""
Dear User,

Your K-Sites analysis has been submitted successfully!

Job Details:
- Job ID: {job.id}
- Organism: {job.organism}
- GO Term: {job.go_term} ({job.go_term_name or 'N/A'})
- Max Genes: {job.max_genes}
- Submitted: {job.created_at.strftime('%Y-%m-%d %H:%M:%S')}

You can track progress at: http://localhost:5000/results/{job.id}

You will receive another email when the analysis is complete.

Best regards,
K-Sites Team
"""
        elif notification_type == 'completed':
            subject = f"K-Sites Analysis Complete - Job {job.id[:8]}"
            body = f"""
Dear User,

Your K-Sites analysis has been completed successfully!

Job Details:
- Job ID: {job.id}
- Organism: {job.organism}
- GO Term: {job.go_term} ({job.go_term_name or 'N/A'})
- Genes Analyzed: {job.genes_processed}
- Completion Time: {job.updated_at.strftime('%Y-%m-%d %H:%M:%S')}

View your results: http://localhost:5000/results/{job.id}

Thank you for using K-Sites!

Best regards,
K-Sites Team
"""
        elif notification_type == 'failed':
            subject = f"K-Sites Analysis Failed - Job {job.id[:8]}"
            body = f"""
Dear User,

We regret to inform you that your K-Sites analysis has failed.

Job Details:
- Job ID: {job.id}
- Organism: {job.organism}
- GO Term: {job.go_term}
- Error: {job.error_message}

Please try again or contact support if the issue persists.

View details: http://localhost:5000/results/{job.id}

Best regards,
K-Sites Team
"""
        else:
            return
        
        msg = Message(subject, recipients=[job.user_email], body=body)
        mail.send(msg)
        logger.info(f"Email sent to {job.user_email} for job {job.id}")
        
    except Exception as e:
        logger.error(f"Failed to send email: {e}")


# ============================================================================
# Login Required Decorator
# ============================================================================

def _token_is_valid() -> bool:
    """True when hosted mode is on and the request carries the correct access token."""
    if not HOSTED_MODE:
        return False
    supplied = request.headers.get('X-KSites-Token', '')
    return hmac.compare_digest(supplied.encode('utf-8'), ACCESS_TOKEN.encode('utf-8'))


def login_required(f):
    """Decorator to require login (local session) or the lab access token (hosted mode)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if HOSTED_MODE:
            if not _token_is_valid():
                return jsonify({'error': 'Authentication required: missing or wrong access token'}), 401
        elif 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.before_request
def hosted_mode_api_only():
    """In hosted mode the pages live on GitHub Pages; this server only answers API calls."""
    if not HOSTED_MODE or request.path.startswith('/api/'):
        return None
    return (
        "K-Sites backend is running. Open the K-Sites website to use it.\n", 200,
        {'Content-Type': 'text/plain; charset=utf-8'}
    )


@app.route('/api/health')
def health():
    """Open endpoint the website uses to wake the backend and check it is reachable."""
    return jsonify({'status': 'ok', 'hosted': HOSTED_MODE, 'version': '1.2.1'})


@app.route('/api/auth/check')
@login_required
def auth_check():
    """Lets the website confirm that the access token it holds is accepted."""
    return jsonify({'ok': True, 'hosted': HOSTED_MODE})


# ============================================================================
# Routes - Authentication
# ============================================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login/Registration page"""
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        institute = request.form.get('institute', '').strip()
        country = request.form.get('country', '').strip()
        
        # Validate inputs
        if not all([name, email, institute, country]):
            flash('All fields are required.', 'error')
            return render_template('login.html')
        
        # Check if user exists
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Update last login
            user.last_login = datetime.utcnow()
        else:
            # Create new user
            user = User(
                name=name,
                email=email,
                institute=institute,
                country=country
            )
            db.session.add(user)
        
        db.session.commit()
        
        # Set session
        session['user_id'] = user.id
        session['user_name'] = user.name
        session['user_email'] = user.email
        
        flash(f'Welcome, {user.name}!', 'success')
        
        # Redirect to next page or index
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        return redirect(url_for('index'))
    
    # If already logged in, redirect to index
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Logout user"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


@app.route('/profile')
@login_required
def profile():
    """User profile page"""
    user = User.query.get(session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))
    return render_template('profile.html', user=user)


# ============================================================================
# Routes - Main Pages
# ============================================================================

@app.route('/')
@login_required
def index():
    """Main page with analysis form"""
    return render_template('index.html', user_name=session.get('user_name'))


@app.route('/results/<job_id>')
@login_required
def view_results(job_id):
    """View analysis results page"""
    job = AnalysisJob.query.get(job_id)
    if not job:
        return render_template('error.html', message='Job not found'), 404
    return render_template('results.html', job=job.to_dict())


@app.route('/jobs')
@login_required
def list_jobs():
    """List all analysis jobs"""
    return render_template('jobs.html')


@app.route('/help')
@login_required
def help_page():
    """Help and documentation page"""
    return render_template('help.html',
                          analytical_terms=ANALYTICAL_TERMS,
                          methodology_sections=METHODOLOGY_SECTIONS,
                          faq_items=FAQ_ITEMS)


# ============================================================================
# API Endpoints - Hierarchical Selection
# ============================================================================

@app.route('/api/organisms/kingdoms')
@login_required
def get_organism_kingdoms():
    """Get list of organism kingdoms/categories"""
    return jsonify({'kingdoms': get_kingdoms()})


@app.route('/api/organisms/by-kingdom')
@login_required
def get_organisms_by_kingdom():
    """Get organisms filtered by kingdom with optional search"""
    kingdom = request.args.get('kingdom')
    query = request.args.get('q', '').strip()
    
    results = search_organisms_by_kingdom(kingdom, query if query else None)
    return jsonify({'results': results, 'kingdom': kingdom, 'query': query})


@app.route('/api/go-terms/categories')
@login_required
def get_go_categories_api():
    """Get list of GO term categories/namespaces"""
    return jsonify({'categories': get_go_categories()})


@app.route('/api/go-terms/by-category')
@login_required
def get_go_terms_by_category():
    """Get GO terms filtered by category with optional search"""
    category = request.args.get('category')
    query = request.args.get('q', '').strip()
    
    results = search_go_terms_by_category(category, query if query else None)
    return jsonify({'results': results, 'category': category, 'query': query})


# ============================================================================
# API Endpoints - Legacy Search (for backwards compatibility)
# ============================================================================

@app.route('/api/organisms/search')
@login_required
def search_organisms_api():
    """Search for organisms by scientific name (legacy)"""
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify({'results': []})
    
    results = search_organisms_by_kingdom(None, query)
    return jsonify({'results': results, 'query': query})


@app.route('/api/go-terms/search')
@login_required
def search_go_terms_api():
    """Search for GO terms by keyword or ID (legacy)"""
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify({'results': []})
    
    results = search_go_terms_by_category(None, query)
    return jsonify({'results': results, 'query': query})


# ============================================================================
# API Endpoints - Databases & Configuration
# ============================================================================

@app.route('/api/databases')
@login_required
def get_databases():
    """Get list of available databases for analysis"""
    databases = [
        {
            'id': 'quickgo',
            'name': 'QuickGO',
            'description': 'Gene Ontology annotations from EBI (always used)',
            'enabled': True,
            'required': True
        },
        {
            'id': 'uniprot',
            'name': 'UniProt',
            'description': 'Protein knowledgebase with functional annotation',
            'enabled': True,
            'required': False
        },
        {
            'id': 'ncbi',
            'name': 'NCBI Entrez',
            'description': 'Gene and genome database',
            'enabled': True,
            'required': False
        },
        {
            'id': 'pubmed',
            'name': 'PubMed',
            'description': 'Literature mining for phenotype evidence',
            'enabled': True,
            'required': False
        },
        {
            'id': 'kegg',
            'name': 'KEGG',
            'description': 'Pathway annotations (pathway count per gene)',
            'enabled': True,
            'required': False
        }
    ]
    
    return jsonify({'databases': databases})


# ============================================================================
# API Endpoints - Analysis
# ============================================================================

@app.route('/api/analyze/validate', methods=['POST'])
@login_required
def validate_analysis():
    """Validate analysis parameters before starting"""
    data = request.json
    
    organism = data.get('organism', '').strip()
    go_term = data.get('go_term', '').strip()
    max_genes = int(data.get('max_genes', 10))
    evidence_filter = data.get('evidence_filter', 'experimental')
    max_pleiotropy = data.get('max_pleiotropy', 5)
    
    errors = []
    warnings = []
    
    # Validate organism
    if not organism:
        errors.append('Organism is required')
    
    # Validate GO term
    if not go_term:
        errors.append('GO term is required')
    elif not go_term.upper().startswith('GO:'):
        errors.append('GO term must be in format GO:XXXXXXX')
    
    # Validate pleiotropy cutoff (the 0-10 pleiotropy score)
    try:
        if not 0 <= int(max_pleiotropy) <= 10:
            errors.append('Max pleiotropy must be between 0 and 10')
    except (TypeError, ValueError):
        errors.append('Max pleiotropy must be a number between 0 and 10')
    
    # Validate evidence type
    if evidence_filter not in ('experimental', 'computational', 'all'):
        errors.append('Evidence filter must be experimental, computational or all')
    
    # Validate max_genes
    if max_genes < 1:
        errors.append('Maximum genes must be at least 1')
    elif max_genes > 500:
        errors.append('Genes to report must be at most 500')
    
    # Check gene count estimate
    try:
        if organism and go_term:
            organism_info = resolve_organism(organism)
            taxid = organism_info['taxid']
            genes = get_genes_for_go_term(go_term, taxid, evidence_filter=evidence_filter)
            total_genes = len(genes)
            
            if total_genes == 0:
                errors.append(f'No genes found for {go_term} in {organism}. Try a different GO term or organism.')
            elif max_genes > total_genes:
                warnings.append(f'Only {total_genes} genes available. Analysis will use all available genes.')
            elif total_genes > max_genes:
                warnings.append(f'{total_genes} genes found. Will process top {max_genes} by specificity.')
            
            # Estimate time
            estimated_seconds = estimate_analysis_time(max_genes, data.get('predict_phenotypes', False))
            
            return jsonify({
                'valid': len(errors) == 0,
                'errors': errors,
                'warnings': warnings,
                'gene_count': total_genes,
                'organism_resolved': organism_info.get('scientific_name'),
                'taxid': taxid,
                'estimated_time_seconds': estimated_seconds,
                'estimated_time_formatted': format_duration(estimated_seconds)
            })
            
    except Exception as e:
        logger.warning(f"Could not validate gene count: {e}")
        warnings.append(f'Could not validate gene count: {str(e)}')
    
    return jsonify({
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    })


def estimate_analysis_time(num_genes: int, predict_phenotypes: bool) -> int:
    """Estimate analysis time in seconds"""
    base_time = 60  # Startup overhead
    per_gene_time = 30  # Basic analysis per gene
    
    if predict_phenotypes:
        per_gene_time += 60  # Add time for RAG phenotype prediction
    
    return base_time + (num_genes * per_gene_time)


def format_duration(seconds: int) -> str:
    """Format duration in human-readable format"""
    if seconds < 60:
        return f"{seconds} seconds"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours} hour{'s' if hours > 1 else ''} {minutes} min"


@app.route('/api/analyze/start', methods=['POST'])
@login_required
def start_analysis():
    """Start a new analysis job"""
    data = request.json
    
    try:
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Estimate completion time
        estimated_seconds = estimate_analysis_time(
            int(data.get('max_genes', 10)),
            data.get('predict_phenotypes', False)
        )
        estimated_completion = datetime.utcnow() + timedelta(seconds=estimated_seconds)
        
        # Create job record
        job = AnalysisJob(
            id=job_id,
            user_id=session.get('user_id'),
            user_email=session.get('user_email') or data.get('user_email') or request.headers.get('X-KSites-User-Email'),
            organism=data.get('organism'),
            taxid=data.get('taxid'),
            go_term=data.get('go_term'),
            go_term_name=data.get('go_term_name'),
            max_genes=int(data.get('max_genes', 10)),
            max_pleiotropy=max(0, min(10, int(data.get('max_pleiotropy', 5)))),
            evidence_filter=data.get('evidence_filter', 'experimental'),
            predict_phenotypes=data.get('predict_phenotypes', False),
            selected_databases=json.dumps(data.get('databases', ['quickgo'])),
            status='pending',
            current_step='Initializing',
            progress_percent=0,
            estimated_completion=estimated_completion
        )
        
        db.session.add(job)
        db.session.commit()
        
        # Send notification email
        send_job_notification(job, 'submitted')
        
        # Start analysis in background
        thread = threading.Thread(target=run_analysis_job, args=(job_id,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'job_id': job_id,
            'status': 'pending',
            'estimated_completion': estimated_completion.isoformat(),
            'message': 'Analysis started successfully'
        })
        
    except Exception as e:
        logger.error(f"Error starting analysis: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def update_job_progress(job_id: str, step: str, percent: int):
    """Update job progress"""
    with app.app_context():
        job = AnalysisJob.query.get(job_id)
        if job:
            job.current_step = step
            job.progress_percent = percent
            db.session.commit()


JOB_SLOTS = threading.BoundedSemaphore(MAX_PARALLEL_JOBS)


def run_analysis_job(job_id: str):
    """Wait for a free analysis slot, then run the job."""
    with app.app_context():
        job = AnalysisJob.query.get(job_id)
        if job:
            job.current_step = 'Waiting for a free analysis slot'
            db.session.commit()
    with JOB_SLOTS:
        _run_analysis_job(job_id)


def _run_analysis_job(job_id: str):
    """Run the analysis job with progress tracking"""
    with app.app_context():
        job = AnalysisJob.query.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return
        
        try:
            # Update status
            job.status = 'running'
            job.current_step = 'Resolving organism'
            job.progress_percent = 5
            db.session.commit()
            
            logger.info(f"Starting analysis job {job_id}")
            
            # Step 1: Resolve organism
            organism_info = resolve_organism(job.organism)
            taxid = organism_info['taxid']
            job.taxid = taxid
            job.current_step = 'Fetching genes from GO database'
            job.progress_percent = 15
            db.session.commit()
            
            # Step 2: Get genes for GO term
            genes = get_genes_for_go_term(job.go_term, taxid, evidence_filter=job.evidence_filter)
            job.total_genes_found = len(genes)
            db.session.commit()
            
            if len(genes) == 0:
                raise ValueError(f"No genes found for {job.go_term} in {job.organism}")
            
            # Check if requested max_genes exceeds available
            actual_max_genes = min(job.max_genes, len(genes))
            
            # Create results directory
            job_results_dir = RESULTS_DIR / job_id
            job_results_dir.mkdir(exist_ok=True)
            
            # Step 3: Run pipeline
            job.current_step = 'Running K-Sites pipeline'
            job.progress_percent = 30
            db.session.commit()
            
            # Progress: reading annotations 30-35%, scoring genes 35-60%, assessing genes 60-83%
            progress_ranges = {
                'Reading GO annotations': (30, 5),
                'Scoring genes': (35, 25),
                'Assessing genes': (60, 23),
            }
            last_reported = {'percent': job.progress_percent}

            def report_progress(stage, done, total):
                base, span = progress_ranges.get(stage, (30, 0))
                percent = int(base + span * (done / total if total else 1))
                job.current_step = f"{stage} ({done}/{total})"
                if percent != last_reported['percent']:
                    job.progress_percent = percent
                    last_reported['percent'] = percent
                db.session.commit()

            pipeline_output = run_k_sites_pipeline(
                go_term=job.go_term,
                organism=job.organism,
                max_pleiotropy=job.max_pleiotropy,
                evidence_filter=job.evidence_filter,
                predict_phenotypes=job.predict_phenotypes,
                progress_callback=report_progress
            )
            
            # Update progress during pipeline
            job.current_step = 'Processing results'
            job.progress_percent = 83
            db.session.commit()
            
            # Limit genes if needed
            if len(pipeline_output.get('genes', [])) > job.max_genes:
                pipeline_output['genes'] = pipeline_output['genes'][:job.max_genes]
            
            # Step 4: Generate outputs
            job.current_step = 'Generating reports'
            job.progress_percent = 85
            db.session.commit()
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # HTML report
            html_path = job_results_dir / f"report_{timestamp}.html"
            generate_html_report(pipeline_output, str(html_path))
            
            # JSON results
            json_path = job_results_dir / f"results_{timestamp}.json"
            with open(json_path, 'w') as f:
                json.dump(pipeline_output, f, indent=2, default=str)
            
            # Update job completion
            job.status = 'completed'
            job.current_step = 'Completed'
            job.progress_percent = 100
            job.genes_processed = len(pipeline_output.get('genes', []))
            job.results_path = str(job_results_dir)
            db.session.commit()
            
            # Send completion email
            send_job_notification(job, 'completed')
            
            logger.info(f"Analysis job {job_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Analysis job {job_id} failed: {e}")
            job.status = 'failed'
            job.current_step = 'Failed'
            job.error_message = str(e)
            db.session.commit()
            
            # Send failure email
            send_job_notification(job, 'failed')


# ============================================================================
# API Endpoints - Job Status & Results
# ============================================================================

@app.route('/api/jobs/<job_id>/status')
@login_required
def get_job_status(job_id):
    """Get job status"""
    job = AnalysisJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify(job.to_dict())


@app.route('/api/jobs')
@login_required
def list_all_jobs():
    """List all analysis jobs"""
    jobs = AnalysisJob.query.order_by(AnalysisJob.created_at.desc()).all()
    return jsonify({'jobs': [job.to_dict() for job in jobs]})


@app.route('/api/jobs/<job_id>/results')
@login_required
def get_job_results(job_id):
    """Get job results"""
    job = AnalysisJob.query.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    if job.status != 'completed':
        return jsonify({
            'status': job.status,
            'current_step': job.current_step,
            'progress_percent': job.progress_percent,
            'message': f'Results not available (status: {job.status})'
        })
    
    # Load results from JSON file
    try:
        results_dir = Path(job.results_path)
        json_files = list(results_dir.glob('results_*.json'))
        
        if json_files:
            with open(json_files[0], 'r') as f:
                results = json.load(f)
            return jsonify({
                'status': 'completed',
                'results': results
            })
        else:
            return jsonify({'error': 'Results file not found'}), 404
            
    except Exception as e:
        logger.error(f"Error loading results: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/jobs/<job_id>/download/<file_type>')
@login_required
def download_results(job_id, file_type):
    """Download result files"""
    job = AnalysisJob.query.get(job_id)
    if not job or job.status != 'completed':
        return jsonify({'error': 'Results not available'}), 404
    
    results_dir = Path(job.results_path)
    
    if file_type == 'html':
        files = list(results_dir.glob('report_*.html'))
        mime_type = 'text/html'
    elif file_type == 'json':
        files = list(results_dir.glob('results_*.json'))
        mime_type = 'application/json'
    elif file_type == 'csv':
        files = list(results_dir.glob('report_*_comprehensive.csv'))
        mime_type = 'text/csv'
    elif file_type == 'summary':
        files = list(results_dir.glob('report_*_gene_summary.csv'))
        mime_type = 'text/csv'
    elif file_type == 'xlsx':
        files = list(results_dir.glob('report_*_comprehensive.xlsx'))
        mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        return jsonify({'error': 'Invalid file type'}), 400
    
    if files:
        return send_file(files[0], mimetype=mime_type, as_attachment=True)
    else:
        return jsonify({'error': 'File not found'}), 404


# ============================================================================
# Error Handlers
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("K-Sites Web Application - Suite for Knock-out/down Studies")
    print("=" * 70)
    print(f"Results directory: {RESULTS_DIR}")
    print(f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print("=" * 70)
    print(f"Starting server on http://127.0.0.1:{os.environ.get('PORT', 5000)}")
    print(f"Help documentation at: http://127.0.0.1:{os.environ.get('PORT', 5000)}/help")
    print("=" * 70)
    
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    app.run(host=host, port=port, debug=not HOSTED_MODE)
