"""
Secure, OpenClaw-compliant configuration system for K-Sites.

This module implements a hierarchical configuration system that follows OpenClaw conventions.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
import logging
from dataclasses import dataclass, field
from dataclasses_json import dataclass_json


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass_json
@dataclass
class NcbiConfig:
    """NCBI API configuration settings."""
    email: str = "user@example.com"  # Required by NCBI E-Utils
    api_key: Optional[str] = None    # Optional but recommended


@dataclass_json
@dataclass
class PipelineConfig:
    """Pipeline configuration settings."""
    max_pleiotropy: int = 3
    cache_dir: str = "~/.openclaw/workspace/k-sites/.cache"


@dataclass_json
@dataclass
class ReportingConfig:
    """Reporting configuration settings."""
    include_literature: bool = True
    max_pubmed_results: int = 5


@dataclass_json
@dataclass
class KSitesConfig:
    """Main K-Sites configuration."""
    ncbi: NcbiConfig = field(default_factory=NcbiConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)


class ConfigLoader:
    """Loads configuration from multiple sources following priority hierarchy."""
    
    def __init__(self):
        self.config_dirs = [
            Path.home() / ".openclaw" / "workspace" / "k-sites" / "config",
            Path.cwd()
        ]
    
    def load_config(self, cli_overrides: Optional[Dict[str, Any]] = None) -> KSitesConfig:
        """
        Load configuration following the priority hierarchy:
        1. CLI flags (highest)
        2. ~/.openclaw/workspace/k-sites/config/k-sites.yaml (user-specific)
        3. ./k-sites.yaml (project-local, git-ignored)
        4. Environment variables
        5. Built-in defaults (lowest)
        """
        config = KSitesConfig()
        
        # Start with built-in defaults
        logger.debug("Starting with built-in defaults")
        
        # Load from YAML files (lower priority than CLI/env vars)
        for config_path in self._get_config_file_paths():
            if config_path.exists():
                logger.info(f"Loading config from {config_path}")
                file_config = self._load_yaml_config(config_path)
                config = self._merge_configs(config, file_config)
        
        # Override with environment variables
        config = self._apply_env_vars(config)
        
        # Override with CLI flags (highest priority)
        if cli_overrides:
            logger.debug("Applying CLI overrides")
            config = self._apply_cli_overrides(config, cli_overrides)
        
        # Validate configuration
        self._validate_config(config)
        
        return config
    
    def _get_config_file_paths(self) -> list:
        """Get list of potential config file paths in priority order."""
        paths = []
        
        # User-specific config (higher priority than project config)
        user_config = self.config_dirs[0] / "k-sites.yaml"
        if user_config.exists():
            paths.append(user_config)
        
        # Project-local config
        project_config = Path("k-sites.yaml")
        if project_config.exists():
            paths.append(project_config)
        
        return paths
    
    def _load_yaml_config(self, config_path: Path) -> KSitesConfig:
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as f:
                yaml_data = yaml.safe_load(f)
                
            if yaml_data is None:
                return KSitesConfig()  # Return defaults if file is empty
            
            # Handle environment variable substitution in strings
            yaml_data = self._resolve_env_vars(yaml_data)
            
            # Convert to KSitesConfig - handle nested structures properly
            config_dict = {}
            
            if 'ncbi' in yaml_data:
                ncbi_data = yaml_data.get('ncbi', {})
                config_dict['ncbi'] = NcbiConfig(
                    email=ncbi_data.get('email', 'user@example.com'),
                    api_key=ncbi_data.get('api_key')
                )
            else:
                config_dict['ncbi'] = NcbiConfig()
            
            if 'pipeline' in yaml_data:
                pipeline_data = yaml_data.get('pipeline', {})
                config_dict['pipeline'] = PipelineConfig(
                    max_pleiotropy=pipeline_data.get('max_pleiotropy', 3),
                    cache_dir=pipeline_data.get('cache_dir', '~/.openclaw/workspace/k-sites/.cache')
                )
            else:
                config_dict['pipeline'] = PipelineConfig()
            
            if 'reporting' in yaml_data:
                reporting_data = yaml_data.get('reporting', {})
                config_dict['reporting'] = ReportingConfig(
                    include_literature=reporting_data.get('include_literature', True),
                    max_pubmed_results=reporting_data.get('max_pubmed_results', 5)
                )
            else:
                config_dict['reporting'] = ReportingConfig()
            
            return KSitesConfig(**config_dict)
            
        except Exception as e:
            logger.error(f"Error loading config from {config_path}: {e}")
            raise
    
    def _resolve_env_vars(self, data: Any) -> Any:
        """Recursively resolve environment variables in config data."""
        if isinstance(data, str):
            # Look for ${VAR_NAME} pattern and replace with env var value
            import re
            pattern = r'\$\{([^}]+)\}'
            
            def replace_var(match):
                var_name = match.group(1)
                value = os.getenv(var_name)
                if value is None:
                    logger.warning(f"Environment variable {var_name} not found, leaving as is")
                    return match.group(0)  # Return original if not found
                return value
            
            return re.sub(pattern, replace_var, data)
        elif isinstance(data, dict):
            return {key: self._resolve_env_vars(value) for key, value in data.items()}
        elif isinstance(data, list):
            return [self._resolve_env_vars(item) for item in data]
        else:
            return data
    
    def _apply_env_vars(self, config: KSitesConfig) -> KSitesConfig:
        """Apply environment variables to configuration."""
        # NCBI settings
        if os.getenv('K_SITES_NCBI_EMAIL'):
            config.ncbi.email = os.getenv('K_SITES_NCBI_EMAIL')
        if os.getenv('K_SITES_NCBI_API_KEY'):
            config.ncbi.api_key = os.getenv('K_SITES_NCBI_API_KEY')
        
        # Pipeline settings
        if os.getenv('K_SITES_MAX_PLEIOTROPY'):
            config.pipeline.max_pleiotropy = int(os.getenv('K_SITES_MAX_PLEIOTROPY'))
        
        # Reporting settings
        if os.getenv('K_SITES_INCLUDE_LITERATURE'):
            config.reporting.include_literature = os.getenv('K_SITES_INCLUDE_LITERATURE', '').lower() in ('true', '1', 'yes')
        if os.getenv('K_SITES_MAX_PUBMED_RESULTS'):
            config.reporting.max_pubmed_results = int(os.getenv('K_SITES_MAX_PUBMED_RESULTS'))
        
        return config
    
    def _apply_cli_overrides(self, config: KSitesConfig, overrides: Dict[str, Any]) -> KSitesConfig:
        """Apply CLI overrides to configuration."""
        # Apply overrides with dot notation support (e.g., "ncbi.email")
        for key, value in overrides.items():
            if '.' in key:
                parts = key.split('.')
                current = config
                
                # Navigate to the nested attribute
                for part in parts[:-1]:
                    current = getattr(current, part)
                
                # Set the final value
                setattr(current, parts[-1], value)
            else:
                # Direct attribute
                if hasattr(config, key):
                    setattr(config, key, value)
        
        return config
    
    def _merge_configs(self, base: KSitesConfig, override: KSitesConfig) -> KSitesConfig:
        """Merge two configurations, with override taking precedence."""
        # For each section, update with values from override
        base.ncbi = NcbiConfig(
            email=override.ncbi.email if override.ncbi.email != "user@example.com" else base.ncbi.email,
            api_key=override.ncbi.api_key if override.ncbi.api_key is not None else base.ncbi.api_key
        )
        
        base.pipeline = PipelineConfig(
            max_pleiotropy=override.pipeline.max_pleiotropy if override.pipeline.max_pleiotropy != 3 else base.pipeline.max_pleiotropy,
            cache_dir=override.pipeline.cache_dir if override.pipeline.cache_dir != "~/.openclaw/workspace/k-sites/.cache" else base.pipeline.cache_dir
        )
        
        base.reporting = ReportingConfig(
            include_literature=override.reporting.include_literature if override.reporting.include_literature != True else base.reporting.include_literature,
            max_pubmed_results=override.reporting.max_pubmed_results if override.reporting.max_pubmed_results != 5 else base.reporting.max_pubmed_results
        )
        
        return base
    
    def _validate_config(self, config: KSitesConfig) -> None:
        """Validate configuration values."""
        errors = []
        
        # Validate NCBI email (required by NCBI E-Utils)
        if not config.ncbi.email or config.ncbi.email == "user@example.com":
            errors.append("NCBI email is required and must be a valid email address")
        
        # Validate max_pleiotropy is positive
        if config.pipeline.max_pleiotropy < 0:
            errors.append("max_pleiotropy must be non-negative")
        
        # Validate max_pubmed_results is positive
        if config.reporting.max_pubmed_results <= 0:
            errors.append("max_pubmed_results must be positive")
        
        if errors:
            raise ValueError("Configuration validation failed:\n" + "\n".join(errors))


# Global config loader instance
_config_loader = ConfigLoader()


def get_config(cli_overrides: Optional[Dict[str, Any]] = None) -> KSitesConfig:
    """
    Get the current configuration, loading it if necessary.
    
    Args:
        cli_overrides: Optional dictionary of CLI flag overrides
        
    Returns:
        KSitesConfig instance with loaded configuration
    """
    return _config_loader.load_config(cli_overrides)


def create_default_config(config_path: Path) -> None:
    """
    Create a default configuration file at the specified path.
    
    Args:
        config_path: Path where the default config should be created
    """
    default_config = KSitesConfig()
    
    # Create parent directories if they don't exist
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert to dict for YAML serialization
    config_dict = {
        "ncbi": {
            "email": default_config.ncbi.email,
            "api_key": default_config.ncbi.api_key
        },
        "pipeline": {
            "max_pleiotropy": default_config.pipeline.max_pleiotropy,
            "cache_dir": default_config.pipeline.cache_dir
        },
        "reporting": {
            "include_literature": default_config.reporting.include_literature,
            "max_pubmed_results": default_config.reporting.max_pubmed_results
        }
    }
    
    with open(config_path, 'w') as f:
        yaml.dump(config_dict, f, default_flow_style=False, indent=2)
    
    logger.info(f"Created default configuration file at {config_path}")