"""Insights-core archive processing module."""
import json
import logging
import os
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yaml

from sqlalchemy.orm import Session

# Insights-core imports matching ccx-data-pipeline
from insights import apply_configs, apply_default_enabled, dr
from insights.core.archives import extract
from insights.core.hydration import initialize_broker
from insights.formats.text import HumanReadableFormat

from app.config import get_settings
from app.models import Report, RuleHit, ReportInfo

logger = logging.getLogger(__name__)
settings = get_settings()

Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class ProcessingError(Exception):
    """Raised when archive processing fails."""

    pass


def load_insights_config(config_path: str = "config.yml") -> Dict:
    """
    Load insights-core configuration from YAML file.

    Args:
        config_path: Path to the YAML configuration file

    Returns:
        Configuration dictionary matching ccx-data-pipeline structure

    Raises:
        ProcessingError: If config file cannot be loaded
    """
    try:
        if not os.path.exists(config_path):
            logger.warning(f"Config file {config_path} not found, using defaults")
            return {
                "plugins": {"packages": [], "configs": []},
                "service": {
                    "extract_timeout": 300,
                    "extract_tmp_dir": settings.temp_upload_dir,
                    "format": "insights.formats._json.JsonFormat",
                    "target_components": [],
                    "unpacked_archive_size_limit": -1,
                },
                "logging": {},
            }

        with open(config_path, "r") as f:
            config = yaml.load(f, Loader=Loader)

        logger.info(f"Loaded insights-core configuration from {config_path}")
        return config

    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        raise ProcessingError(f"Configuration loading failed: {str(e)}")


def load_insights_components(config: Dict) -> None:
    """
    Load insights-core components based on configuration.
    Matches ccx-data-pipeline's approach using dr.load_components().

    Args:
        config: Configuration dictionary from YAML file
    """
    plugins = config.get("plugins", {})
    packages = plugins.get("packages", [])

    # Load each package using dr.load_components
    loaded_packages = []
    failed_packages = []

    for package in packages:
        try:
            logger.info(f"Loading package: {package}")
            dr.load_components(package, continue_on_error=False)
            loaded_packages.append(package)
        except ImportError as e:
            # Package not available (e.g., ccx packages without Red Hat repo access)
            logger.warning(f"Package {package} not available (may require Red Hat internal repository): {e}")
            failed_packages.append(package)
        except Exception as e:
            logger.error(f"Failed to load package {package}: {e}")
            failed_packages.append(package)

    # Apply default enabled components
    apply_default_enabled(plugins)

    # Apply component-specific configurations
    apply_configs(plugins)

    if loaded_packages:
        logger.info(f"Successfully loaded packages: {', '.join(loaded_packages)}")
    if failed_packages:
        logger.warning(f"Failed to load packages: {', '.join(failed_packages)}")
        logger.warning("Application will continue with basic insights-core functionality")

    logger.info("Insights-core components loading completed")


def get_component_graphs(target_components: List[str]) -> Dict:
    """
    Get dependency graphs for target components.
    Matches ccx-data-pipeline's _get_graphs() method.

    Args:
        target_components: List of component name prefixes

    Returns:
        Dictionary of component dependency graphs
    """
    graph = {}
    tc = tuple(target_components or [])

    if tc:
        for c in dr.DELEGATES:
            if dr.get_name(c).startswith(tc):
                graph.update(dr.get_dependency_graph(c))

    return graph


class ArchiveProcessor:
    """
    Handles processing of Red Hat Insights archives.
    Implementation matches ccx-data-pipeline's approach.
    """

    # Class-level configuration cache
    _config = None
    _config_loaded = False

    def __init__(
        self, db: Session, org_id: int, config_path: str = "config.yml"
    ):
        """
        Initialize the archive processor.

        Args:
            db: Database session
            org_id: Organization ID from authentication
            config_path: Path to insights configuration YAML file
        """
        self.db = db
        self.org_id = org_id

        # Load configuration (cached at class level)
        if not ArchiveProcessor._config_loaded:
            ArchiveProcessor._config = load_insights_config(config_path)
            load_insights_components(ArchiveProcessor._config)
            ArchiveProcessor._config_loaded = True

        self.config = ArchiveProcessor._config
        self.service_config = self.config.get("service", {})

        # Setup formatter
        formatter_name = self.service_config.get("format", "insights.formats._json.JsonFormat")
        self.Formatter = dr.get_component(formatter_name) or HumanReadableFormat

        # Setup target components
        target_components = self.service_config.get("target_components", [])
        if target_components:
            self.components_dict = get_component_graphs(target_components)
        else:
            # Use all single-node components if none specified
            self.components_dict = dr.determine_components(
                dr.COMPONENTS[dr.GROUPS.single]
            )

        self.target_components = dr.toposort_flatten(self.components_dict, sort=False)

        # Extraction settings
        self.extract_timeout = self.service_config.get("extract_timeout", 300)
        self.extract_tmp_dir = self.service_config.get(
            "extract_tmp_dir", settings.temp_upload_dir
        )
        self.unpacked_archive_size_limit = self.service_config.get(
            "unpacked_archive_size_limit", -1
        )

        logger.debug(
            f"Processor initialized with {len(self.target_components)} components"
        )

    def validate_size(self, extraction_path: str) -> bool:
        """
        Validate unpacked archive size.

        Args:
            extraction_path: Path to extracted archive

        Returns:
            True if size is acceptable, False otherwise
        """
        if self.unpacked_archive_size_limit < 0:
            logger.debug("No size limitation for unpacked archive")
            return True

        total_size = sum(p.stat().st_size for p in Path(extraction_path).rglob("*"))

        if total_size >= self.unpacked_archive_size_limit:
            logger.warning(
                f"Unpacked archive exceeds limit: {total_size} >= {self.unpacked_archive_size_limit}"
            )
            return False

        return True

    def get_cluster_id(self, extraction_path: str) -> str:
        """
        Extract cluster ID from archive.

        Args:
            extraction_path: Path to extracted archive directory

        Returns:
            Cluster identifier

        Raises:
            ProcessingError: If cluster ID cannot be determined
        """
        # Try directory name first
        dir_name = os.path.basename(extraction_path)
        if dir_name and dir_name != ".":
            logger.debug(f"Using directory name as cluster_id: {dir_name}")
            return dir_name

        # Try metadata files
        metadata_files = ["metadata.json", "insights_archive_metadata.json"]
        for metadata_file in metadata_files:
            metadata_path = os.path.join(extraction_path, metadata_file)
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)
                        if "cluster_id" in metadata:
                            return metadata["cluster_id"]
                except Exception as e:
                    logger.warning(f"Failed to read metadata from {metadata_file}: {e}")

        raise ProcessingError("Could not determine cluster ID from archive")

    def process_with_insights_core(
        self, archive_path: str
    ) -> Tuple[str, str, Dict]:
        """
        Process archive with insights-core using ccx-data-pipeline approach.

        Args:
            archive_path: Path to archive file

        Returns:
            Tuple of (cluster_id, results_json, version_info)

        Raises:
            ProcessingError: If processing fails
        """
        try:
            logger.info(f"Processing archive: {archive_path}")

            # Use insights.core.archives.extract() like ccx-data-pipeline
            with extract(
                archive_path,
                timeout=self.extract_timeout,
                extract_dir=self.extract_tmp_dir,
            ) as extraction:
                # Validate size
                if not self.validate_size(extraction.tmp_dir):
                    raise ProcessingError(
                        f"Archive exceeds size limit: {self.unpacked_archive_size_limit}"
                    )

                # Get cluster ID
                cluster_id = self.get_cluster_id(extraction.tmp_dir)
                logger.info(f"Processing cluster: {cluster_id}")

                # Initialize broker like ccx-data-pipeline
                ctx, broker = initialize_broker(extraction.tmp_dir)

                # Run components with formatter
                output = StringIO()
                with self.Formatter(broker, stream=output):
                    dr.run_components(
                        self.target_components, self.components_dict, broker=broker
                    )

                output.seek(0)
                result = output.read()

                logger.info(f"Processing completed for cluster {cluster_id}")
                logger.debug(f"Result length: {len(result)} chars")

                # Extract version info
                version_info = {
                    "insights_core_version": "unknown",
                    "processed_at": datetime.utcnow().isoformat(),
                    "formatter": str(self.Formatter),
                    "components_count": len(self.target_components),
                }

                return cluster_id, result, version_info

        except Exception as e:
            logger.error(f"insights-core processing failed: {e}", exc_info=True)
            raise ProcessingError(f"Analysis failed: {str(e)}")

    def extract_rule_hits(self, results_json: str) -> List[Dict]:
        """
        Extract rule hits from insights-core results.

        Args:
            results_json: JSON string from insights-core

        Returns:
            List of rule hit dictionaries with rule_fqdn, error_key, and content metadata
        """
        rule_hits = []

        try:
            # Parse JSON results
            if not results_json or results_json == "{}":
                logger.info("No results to parse")
                return rule_hits

            results = json.loads(results_json)

            # Extract rules based on format
            # The format depends on the Formatter used
            # For JsonFormat, results typically contain component outputs

            # This is a simplified extraction - adjust based on actual format
            if isinstance(results, dict):
                for key, value in results.items():
                    if "error" in key.lower() or "rule" in key.lower():
                        # Extract content metadata from value
                        if isinstance(value, dict):
                            content = {
                                "description": value.get("description", ""),
                                "generic": value.get("generic", ""),
                                "reason": value.get("reason", ""),
                                "resolution": value.get("resolution", ""),
                                "more_info": value.get("more_info", ""),
                                "total_risk": value.get("total_risk", 1),
                                "likelihood": value.get("likelihood", 1),
                                "impact": value.get("impact", 1),
                                "publish_date": value.get("publish_date"),
                                "tags": json.dumps(value.get("tags", [])),
                            }
                        else:
                            content = {
                                "description": str(value),
                                "generic": "",
                                "reason": "",
                                "resolution": "",
                                "more_info": "",
                                "total_risk": 1,
                                "likelihood": 1,
                                "impact": 1,
                                "publish_date": None,
                                "tags": "[]",
                            }

                        rule_hits.append(
                            {
                                "rule_fqdn": key,
                                "error_key": "GENERIC_ERROR",
                                "content": content,
                            }
                        )

            logger.info(f"Extracted {len(rule_hits)} rule hits")

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse results JSON: {e}")
        except Exception as e:
            logger.warning(f"Error extracting rule hits: {e}")

        return rule_hits

    def save_results(
        self,
        cluster_id: str,
        results_json: str,
        version_info: Dict,
    ) -> int:
        """
        Save processing results to database.

        Args:
            cluster_id: Cluster identifier
            results_json: JSON results from insights-core
            version_info: Version information dictionary

        Returns:
            Number of rule hits saved
        """
        # Extract rule hits from results
        rule_hits = self.extract_rule_hits(results_json)

        # Save main report
        report_data = {
            "cluster_id": cluster_id,
            "rule_count": len(rule_hits),
            "processed_at": datetime.utcnow().isoformat(),
            "results": results_json,
        }

        Report.upsert(
            self.db,
            org_id=self.org_id,
            cluster=cluster_id,
            report=json.dumps(report_data),
            gathered_at=datetime.utcnow(),
        )

        # Clear existing rule hits for this cluster
        RuleHit.delete_for_cluster(self.db, self.org_id, cluster_id)

        # Save new rule hits (just references - content served from files)
        for hit in rule_hits:
            RuleHit.upsert(
                self.db,
                org_id=self.org_id,
                cluster_id=cluster_id,
                rule_fqdn=hit["rule_fqdn"],
                error_key=hit["error_key"],
            )

        # Save report info
        ReportInfo.upsert(
            self.db,
            org_id=self.org_id,
            cluster_id=cluster_id,
            version_info=json.dumps(version_info),
        )

        logger.info(f"Saved {len(rule_hits)} rule hits for cluster {cluster_id}")
        return len(rule_hits)

    def process_archive(self, archive_path: str) -> Tuple[str, int]:
        """
        Main processing function - extract, analyze, and save archive.

        Args:
            archive_path: Path to uploaded archive file

        Returns:
            Tuple of (cluster_id, number of rules found)

        Raises:
            ProcessingError: If processing fails at any stage
        """
        logger.info(f"Starting archive processing: {archive_path}")

        # Process with insights-core (ccx-data-pipeline approach)
        cluster_id, results_json, version_info = self.process_with_insights_core(
            archive_path
        )

        # Save to database
        rules_count = self.save_results(cluster_id, results_json, version_info)

        logger.info(f"Completed processing for cluster {cluster_id}")
        return cluster_id, rules_count
