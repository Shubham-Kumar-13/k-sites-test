"""
K-Sites Web Application Configuration
"""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)

# Flask Configuration
class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(24)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Database
    # KSITES_DATABASE_URI can point to PostgreSQL, MySQL, etc. Default is local SQLite.
    SQLALCHEMY_DATABASE_URI = os.environ.get('KSITES_DATABASE_URI') or f'sqlite:///{RESULTS_DIR}/ksites_jobs.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # K-Sites Configuration
    K_SITES_NCBI_EMAIL = os.environ.get('K_SITES_NCBI_EMAIL') or 'user@example.com'
    K_SITES_NCBI_API_KEY = os.environ.get('K_SITES_NCBI_API_KEY')
    


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    
    # Use environment variable for secret key in production
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # More secure session settings
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
