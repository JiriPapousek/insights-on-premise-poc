"""
Parse rule content from markdown/YAML files.

This module reads rule metadata from the content/ directory structure
that matches the format used by insights-content-service.
"""
import logging
import yaml
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class YAMLContentParser:
    """Parser for extracting rule metadata from markdown/YAML content files."""

    def __init__(self, content_path: str = None):
        """
        Initialize the parser.

        :param content_path: Path to rules-content directory. If None, use default.
        """
        if content_path is None:
            # Default to rules-content in project root
            self.content_path = Path(__file__).parent.parent / "rules-content"
        else:
            self.content_path = Path(content_path)

        if not self.content_path.exists():
            logger.warning(f"Content path {self.content_path} does not exist")
            self.content_path = None

    def parse_all_rules(self) -> List[Dict]:
        """
        Parse all rule files and extract metadata.

        :return: List of rule content dictionaries
        """
        if not self.content_path:
            logger.warning("Content path not available, skipping parsing")
            return []

        rules_content = []

        # Parse external rules
        external_rules_path = self.content_path / "external" / "rules"
        if external_rules_path.exists():
            rules_content.extend(self._parse_rules_directory(external_rules_path, "external"))

        # Parse internal rules
        internal_rules_path = self.content_path / "internal" / "rules"
        if internal_rules_path.exists():
            rules_content.extend(self._parse_rules_directory(internal_rules_path, "internal"))

        logger.info(f"Parsed {len(rules_content)} rule content entries from {self.content_path}")
        return rules_content

    def _parse_rules_directory(self, rules_dir: Path, rule_type: str) -> List[Dict]:
        """
        Parse all rules in a directory (external or internal).

        :param rules_dir: Path to rules directory
        :param rule_type: Type of rules (external/internal)
        :return: List of rule content dictionaries
        """
        rules_content = []

        # Each subdirectory is a rule
        for rule_dir in rules_dir.iterdir():
            if not rule_dir.is_dir() or rule_dir.name.startswith("."):
                continue

            try:
                rule_content = self._parse_rule_directory(rule_dir, rule_type)
                if rule_content:
                    rules_content.extend(rule_content)
            except Exception as e:
                logger.warning(f"Failed to parse {rule_dir.name}: {e}")

        return rules_content

    def _parse_rule_directory(self, rule_dir: Path, rule_type: str) -> List[Dict]:
        """
        Parse a single rule directory.

        :param rule_dir: Path to rule directory
        :param rule_type: Type of rule (external/internal)
        :return: List of rule content dictionaries (one per error key)
        """
        rule_name = rule_dir.name
        module_name = f"ccx_rules_ocp.{rule_type}.rules.{rule_name}"

        # Read plugin.yaml
        plugin_file = rule_dir / "plugin.yaml"
        if not plugin_file.exists():
            logger.warning(f"No plugin.yaml found for {rule_name}")
            return []

        with open(plugin_file, "r", encoding="utf-8") as f:
            plugin_data = yaml.safe_load(f)

        # Get plugin metadata
        plugin_info = plugin_data.get("plugin", {})

        # Find all error key directories
        error_key_dirs = [d for d in rule_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]

        rules = []
        for error_key_dir in error_key_dirs:
            error_key = error_key_dir.name

            try:
                content = self._parse_error_key_directory(error_key_dir)

                # Merge with plugin-level metadata
                # Handle impact - can be a string or int in metadata
                impact_value = content.get("impact", 1)
                if isinstance(impact_value, dict):
                    impact = impact_value.get("impact", 1)
                elif isinstance(impact_value, (int, float)):
                    impact = int(impact_value)
                else:
                    # String value - map common strings to numeric values
                    impact_map = {
                        "low": 1,
                        "medium": 2,
                        "high": 3,
                        "critical": 4,
                    }
                    impact = impact_map.get(str(impact_value).lower(), 2)

                rule_content = {
                    "rule_fqdn": module_name,
                    "error_key": error_key,
                    "description": content.get("generic", ""),
                    "generic": content.get("generic", ""),
                    "reason": content.get("reason", ""),
                    "resolution": content.get("resolution", ""),
                    "more_info": content.get("more_info", ""),
                    "total_risk": content.get("total_risk", 1),
                    "likelihood": content.get("likelihood", 1),
                    "impact": impact,
                    "publish_date": content.get("publish_date", ""),
                    "tags": content.get("tags", []),  # Store as list
                }

                rules.append(rule_content)

            except Exception as e:
                logger.warning(f"Failed to parse error key {error_key} for {rule_name}: {e}")

        return rules

    def _parse_error_key_directory(self, error_key_dir: Path) -> Dict:
        """
        Parse an error key directory containing metadata and markdown files.

        :param error_key_dir: Path to error key directory
        :return: Dictionary with content metadata
        """
        content = {}

        # Read metadata.yaml if it exists
        metadata_file = error_key_dir / "metadata.yaml"
        if metadata_file.exists():
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = yaml.safe_load(f)
                if metadata:
                    content.update(metadata)

        # Read markdown files
        for md_type in ["generic", "reason", "resolution", "more_info"]:
            md_file = error_key_dir / f"{md_type}.md"
            if md_file.exists():
                with open(md_file, "r", encoding="utf-8") as f:
                    content[md_type] = f.read().strip()

        return content
