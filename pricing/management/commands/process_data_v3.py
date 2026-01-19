import logging
import json
import re
import os
from pathlib import Path
import requests
from django.core.management.base import BaseCommand
from pricing.models_v2 import (
    Variant, ProductCategory,
    MatchRule, CategoryRequirement
)

logger = logging.getLogger(__name__)


class AttributeMatchRuleEngine:
    """
    Mechanical tokenization and rule-based attribute matching engine.
    
    Flow:
    1. For unknown SKUs: fetch attributes via HTTP
    2. Tokenize SKU title + attribute label (word-based, then fallback to substrings)
    3. Find overlapping tokens (candidate matches)
    4. Extract minimal necessary tokens (causal pruning)
    5. Store match rule (minimum length enforced)
    6. Apply rules to new SKUs (word boundary matching)
    """
    
    # Minimum length for a match rule to be valid
    # Word boundary regex (\b) prevents false positives, so we can be permissive
    MIN_MATCH_RULE_LENGTH = 2
    
    # Filter files directory
    FILTERS_DIR = Path(__file__).resolve().parent.parent.parent / 'data' / 'filters'
    
    # Attributes to skip when loading filters (not product attributes)
    SKIP_FILTER_KEYS = {'By Availability', 'Stores', 'By Category'}
    
    def __init__(self):
        # rules[attribute_name] = [{'value': ..., 'match_rule': ...}, ...]
        self.rules = {}
        
        # friendlyName -> attributeName mapping (built from API responses)
        self.friendly_to_attr_name = {}
        
        # category_name -> {friendlyName -> [values]} from filter files
        self.preloaded_filters = {}
    
    def load_rules_from_db(self, stdout=None):
        """Load existing match rules from database."""
        count = 0
        for rule in MatchRule.objects.all():
            attr_name = rule.attribute_name
            if attr_name not in self.rules:
                self.rules[attr_name] = []
            
            # Check for duplicates
            match_pattern = rule.match_pattern
            exists = any(
                r['value'] == rule.attribute_value and r['match_rule'] == match_pattern
                for r in self.rules[attr_name]
            )
            
            if not exists:
                self.rules[attr_name].append({
                    'value': rule.attribute_value,
                    'match_rule': match_pattern,
                    'source_sku': rule.source_sku or '',
                    'source_title': rule.source_title or ''
                })
                count += 1
        
        if stdout:
            stdout.write(f'Loaded {count} rules from database')
        return count
    
    def save_rule_to_db(self, rule, source_sku=None, source_title=None, bulk_buffer=None):
        """
        Save a single rule to database (or buffer for bulk save).
        If bulk_buffer is provided, appends to buffer instead of saving immediately.
        Returns True if created, False if existed.
        """
        attr_name = rule['attribute']
        attr_value = rule['value']
        match_pattern = rule['match_rule']
        
        if bulk_buffer is not None:
            # Bulk mode: append to buffer
            bulk_buffer.append({
                'attribute_name': attr_name,
                'attribute_value': attr_value,
                'match_pattern': match_pattern,
                'source_sku': source_sku or '',
                'source_title': source_title or ''
            })
            return True  # Assume it will be created
        else:
            # Immediate mode: save now
            obj, created = MatchRule.objects.get_or_create(
                attribute_name=attr_name,
                attribute_value=attr_value,
                match_pattern=match_pattern,
                defaults={
                    'source_sku': source_sku or '',
                    'source_title': source_title or ''
                }
            )
            return created
    
    def load_filter_files(self, stdout=None):
        """
        Load all CEX_*.json filter files and store known attribute values.
        Returns count of files loaded.
        """
        if not self.FILTERS_DIR.exists():
            if stdout:
                stdout.write(f'Filters directory not found: {self.FILTERS_DIR}')
            return 0
        
        files_loaded = 0
        for filepath in self.FILTERS_DIR.glob('CEX_*.json'):
            try:
                # Convert filename to category name: CEX_Xbox_360_Consoles.json -> Xbox 360 Consoles
                category_name = filepath.stem.replace('CEX_', '').replace('_', ' ')
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.preloaded_filters[category_name] = {}
                
                for friendly_name, attr_data in data.items():
                    if friendly_name in self.SKIP_FILTER_KEYS:
                        continue
                    
                    options = attr_data.get('options', [])
                    if options:
                        self.preloaded_filters[category_name][friendly_name] = options
                
                files_loaded += 1
            except Exception as e:
                if stdout:
                    stdout.write(f'Error loading {filepath}: {e}')
        
        if stdout:
            stdout.write(f'Loaded {files_loaded} filter files with {sum(len(v) for v in self.preloaded_filters.values())} attribute definitions')
        
        return files_loaded
    
    def register_friendly_name_mapping(self, friendly_name, attr_name):
        """Register mapping from attributeFriendlyName to attributeName."""
        self.friendly_to_attr_name[friendly_name] = attr_name
    
    def get_attr_name_from_friendly(self, friendly_name):
        """Get attributeName from friendlyName."""
        return self.friendly_to_attr_name.get(friendly_name)
    
    def find_matching_category(self, api_category_name):
        """
        Find the preloaded filter category that best matches the API category name.
        Uses fuzzy matching (lowercase, ignore spaces/dashes/underscores).
        """
        def normalize(s):
            """Normalize string for comparison - remove spaces, dashes, underscores."""
            return s.lower().replace('-', '').replace('_', '').replace(' ', '')
        
        api_normalized = normalize(api_category_name)
        
        for preloaded_name in self.preloaded_filters.keys():
            preloaded_normalized = normalize(preloaded_name)
            
            # Exact normalized match (handles "Playstation3" vs "Playstation 3")
            if api_normalized == preloaded_normalized:
                return preloaded_name
            
            # Contains match (API might have extra words)
            if preloaded_normalized in api_normalized or api_normalized in preloaded_normalized:
                return preloaded_name
        
        return None
    
    def pregenerate_rules_for_category(self, api_category_name, stdout=None, bulk_buffer=None):
        """
        Pre-generate rules from filter file for a category.
        Should be called after friendly_to_attr_name mapping is built.
        Returns count of rules created.
        """
        matched_category = self.find_matching_category(api_category_name)
        if not matched_category:
            if stdout:
                stdout.write(f'  No preloaded filters found for category: {api_category_name}')
            return 0
        
        filters = self.preloaded_filters.get(matched_category, {})
        rules_created = 0
        
        # Sort values by length (longest first) so longer rules are stored first
        for friendly_name, values in filters.items():
            attr_name = self.get_attr_name_from_friendly(friendly_name)
            if not attr_name:
                continue
            
            # Sort by length descending - longer values first
            sorted_values = sorted(values, key=len, reverse=True)
            
            for value in sorted_values:
                # Generate rule from value itself
                match_rule = value.lower()
                
                if len(match_rule) < self.MIN_MATCH_RULE_LENGTH:
                    continue
                
                rule = {
                    'attribute': attr_name,
                    'value': value,
                    'match_rule': match_rule
                }
                
                if self.store_rule(rule, source_sku='preloaded', source_title=f'Filter: {matched_category}'):
                    # Add to bulk save buffer (or save immediately if no buffer)
                    self.save_rule_to_db(rule, source_sku='preloaded', source_title=f'Filter: {matched_category}', bulk_buffer=bulk_buffer)
                    rules_created += 1
        
        if stdout and rules_created > 0:
            stdout.write(f'  Pre-generated {rules_created} rules from filter file for "{matched_category}"')
        
        return rules_created
    
    def tokenize_words(self, text):
        """Tokenize into whole words only (split by delimiters)."""
        if not text:
            return set()
        
        tokens = set()
        text_clean = text.strip()
        
        word_tokens = re.split(r'[\/\-\s,\(\):]+', text_clean)
        for token in word_tokens:
            token = token.strip()
            if token and len(token) >= 1:
                tokens.add(token.lower())
        
        for i in range(len(word_tokens)):
            for j in range(i + 1, min(i + 4, len(word_tokens) + 1)):
                combo = ' '.join(t.strip() for t in word_tokens[i:j] if t.strip())
                if combo and len(combo) >= 2:
                    tokens.add(combo.lower())
        
        if len(text_clean) <= 50:
            tokens.add(text_clean.lower())
        
        return tokens
    
    def tokenize_substrings(self, text, min_len=4, max_len=10):
        """Fallback: Generate substring tokens (sliding windows)."""
        if not text:
            return set()
        
        tokens = set()
        text_clean = text.strip().lower()
        
        for window_len in range(min_len, min(max_len + 1, len(text_clean) + 1)):
            for i in range(len(text_clean) - window_len + 1):
                window = text_clean[i:i+window_len].strip()
                if window and len(window) >= min_len:
                    tokens.add(window)
        
        return tokens
    
    def find_candidate_matches(self, title_tokens, label_tokens):
        """Find tokens that appear in both title and label."""
        return title_tokens.intersection(label_tokens)
    
    def word_exists_in_text(self, word, text):
        """Check if a word exists in text with word boundaries."""
        pattern = r'\b' + re.escape(word) + r'\b'
        return bool(re.search(pattern, text, re.IGNORECASE))
    
    def is_grade_or_condition_attribute(self, attribute_name):
        """
        Heuristic: some feeds name this 'grade', others 'condition', others 'item_condition', etc.
        Use substring match (lowercased) so we don't depend on exact naming.
        """
        if not attribute_name:
            return False
        name = attribute_name.strip().lower()
        return ('grade' in name) or ('condition' in name)

    def extract_best_match_rule(self, title, label, candidate_tokens):
        """
        Extract the best match rule from candidates.
        Returns string (contiguous) or list (all must match).
        """
        title_lower = title.lower()
        label_lower = label.lower()
        
        # PRIORITY 1: Exact contiguous match (allow shorter min for exact matches)
        if len(label_lower) >= self.MIN_MATCH_RULE_LENGTH:
            exact_pattern = r'\b' + re.escape(label_lower) + r'\b'
            if re.search(exact_pattern, title_lower, re.IGNORECASE):
                return label_lower
            if ' ' in label_lower and label_lower in title_lower:
                return label_lower
        
        # PRIORITY 2: All words match (non-contiguous)
        label_words = [w.strip().lower() for w in re.split(r'[\/\-\s,\(\):]+', label) if w.strip()]
        significant_words = [w for w in label_words if len(w) >= self.MIN_MATCH_RULE_LENGTH]
        
        if len(significant_words) >= 2:
            all_present = all(self.word_exists_in_text(w, title_lower) for w in significant_words)
            if all_present:
                return significant_words
        
        # PRIORITY 3: Longest candidate
        if not candidate_tokens:
            return None
        
        valid_candidates = [c for c in candidate_tokens if len(c) >= self.MIN_MATCH_RULE_LENGTH]
        if not valid_candidates:
            return None
        
        candidates = sorted(valid_candidates, key=len, reverse=True)
        for candidate in candidates:
            if self.word_exists_in_text(candidate, title_lower):
                return candidate

        # If we couldn't find any candidate that matches as a whole word in the title,
        # do NOT fall back to an arbitrary substring (this creates junk rules like "la").
        return None
    
    def learn_rule_from_sku(self, sku_title, attribute_name, attribute_value):
        """Learn a match rule from a SKU title and attribute label."""
        if not sku_title or not attribute_value:
            return None
        
        # Special case: single-letter values for grade/condition-like attributes.
        # Keep MIN_MATCH_RULE_LENGTH=2 for normal rules to avoid overly-broad matches (e.g. i5),
        # but for grade/condition we can safely use a regex rule that still respects boundaries.
        value_str = str(attribute_value).strip()
        if len(value_str) == 1 and self.is_grade_or_condition_attribute(attribute_name):
            if self.word_exists_in_text(value_str, sku_title):
                return {
                    'attribute': attribute_name,
                    'value': value_str,
                    'match_rule': {'regex': r'\b' + re.escape(value_str.lower()) + r'\b'}
                }
        
        title_words = self.tokenize_words(sku_title)
        label_words = self.tokenize_words(attribute_value)
        word_candidates = self.find_candidate_matches(title_words, label_words)
        match_rule = self.extract_best_match_rule(sku_title, attribute_value, word_candidates)
        
        if not match_rule:
            title_substrings = self.tokenize_substrings(sku_title, min_len=self.MIN_MATCH_RULE_LENGTH)
            label_substrings = self.tokenize_substrings(attribute_value, min_len=self.MIN_MATCH_RULE_LENGTH)
            substring_candidates = self.find_candidate_matches(title_substrings, label_substrings)
            match_rule = self.extract_best_match_rule(sku_title, attribute_value, substring_candidates)
        
        if not match_rule:
            return None
        
        return {
            'attribute': attribute_name,
            'value': attribute_value,
            'match_rule': match_rule
        }
    
    def store_rule(self, rule, source_sku=None, source_title=None):
        """Store a learned rule with source tracking."""
        if not rule:
            return False
        
        match_rule = rule['match_rule']
        
        if isinstance(match_rule, str):
            # Allow shorter rules for exact matches (like "Wii", "PS5")
            if len(match_rule) < self.MIN_MATCH_RULE_LENGTH:
                return False
        elif isinstance(match_rule, list):
            if len(match_rule) < 2:
                return False
            # Array elements still need 4+ chars for safety
            if not all(len(w) >= self.MIN_MATCH_RULE_LENGTH for w in match_rule):
                return False
        elif isinstance(match_rule, dict):
            # Regex rule: {"regex": "..."} (used for grade/condition single-letter values)
            pattern = match_rule.get('regex')
            if not isinstance(pattern, str) or len(pattern) < self.MIN_MATCH_RULE_LENGTH:
                return False
        else:
            return False
        
        attribute_name = rule['attribute']
        if attribute_name not in self.rules:
            self.rules[attribute_name] = []
        
        for existing in self.rules[attribute_name]:
            if existing['value'] == rule['value'] and existing['match_rule'] == match_rule:
                return False
        
        self.rules[attribute_name].append({
            'value': rule['value'],
            'match_rule': match_rule,
            'source_sku': source_sku,
            'source_title': source_title
        })
        return True
    
    def matches_rule(self, text, match_rule):
        """Check if text matches the rule (string or list)."""
        if isinstance(match_rule, str):
            return self.word_exists_in_text(match_rule, text)
        elif isinstance(match_rule, list):
            return all(self.word_exists_in_text(word, text) for word in match_rule)
        elif isinstance(match_rule, dict):
            pattern = match_rule.get('regex')
            if not pattern:
                return False
            return bool(re.search(pattern, text, re.IGNORECASE))
        return False
    
    def apply_rules_to_sku(self, sku_title, required_attributes=None):
        """
        Apply stored match rules to a SKU title.
        If required_attributes is provided, only match those.
        Returns dict of {attribute_name: attribute_value} for matched rules.
        
        FIXED: Now finds the LONGEST/MOST SPECIFIC matching rule instead of first match.
        """
        if not sku_title:
            return {}
        
        matched_attributes = {}
        attributes_to_check = required_attributes if required_attributes else self.rules.keys()
        
        for attribute_name in attributes_to_check:
            # Try existing rules - find BEST match (longest/most specific)
            if attribute_name in self.rules:
                rules_list = self.rules[attribute_name]
                
                # Sort rules by priority (same as before for consistency)
                sorted_rules = sorted(
                    rules_list,
                    key=lambda r: (
                        0 if isinstance(r['match_rule'], list) else (1 if isinstance(r['match_rule'], dict) else 2),
                        -(len(r['match_rule'].get('regex', '')) if isinstance(r['match_rule'], dict)
                        else (len(r['match_rule']) if isinstance(r['match_rule'], str)
                                else sum(len(w) for w in r['match_rule'])))
                    )
                )
                
                # CHANGED: Find ALL matching rules, then pick the best one
                matching_rules = []
                for rule in sorted_rules:
                    match_rule = rule['match_rule']
                    if match_rule and self.matches_rule(sku_title, match_rule):
                        matching_rules.append(rule)
                
                # Pick the MOST SPECIFIC match
                if matching_rules:
                    # Priority 1: Multi-word array rules (most specific)
                    array_matches = [r for r in matching_rules if isinstance(r['match_rule'], list)]
                    if array_matches:
                        # Pick longest total length
                        best = max(array_matches, key=lambda r: sum(len(w) for w in r['match_rule']))
                        matched_attributes[attribute_name] = best['value']
                        continue
                    
                    # Priority 2: Regex rules
                    regex_matches = [r for r in matching_rules if isinstance(r['match_rule'], dict)]
                    if regex_matches:
                        # Pick longest regex pattern
                        best = max(regex_matches, key=lambda r: len(r['match_rule'].get('regex', '')))
                        matched_attributes[attribute_name] = best['value']
                        continue
                    
                    # Priority 3: String rules - pick LONGEST matching string
                    string_matches = [r for r in matching_rules if isinstance(r['match_rule'], str)]
                    if string_matches:
                        best = max(string_matches, key=lambda r: len(r['match_rule']))
                        matched_attributes[attribute_name] = best['value']
                        continue
            
            # Fallback for grade/condition attributes: try matching single letters directly
            # This handles cases where rules exist but haven't matched, or rules haven't been learned yet
            if attribute_name not in matched_attributes and self.is_grade_or_condition_attribute(attribute_name):
                # Get known single-letter values from existing rules (if any)
                known_single_letter_values = set()
                if attribute_name in self.rules:
                    for rule in self.rules[attribute_name]:
                        value_str = str(rule['value']).strip()
                        if len(value_str) == 1:
                            known_single_letter_values.add(value_str.upper())
                
                # If we have known values, only try those; otherwise try common grade letters
                letters_to_try = list(known_single_letter_values) if known_single_letter_values else ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
                
                for letter in letters_to_try:
                    # Use word boundary to match standalone letters
                    pattern = r'\b' + re.escape(letter) + r'\b'
                    if re.search(pattern, sku_title, re.IGNORECASE):
                        matched_attributes[attribute_name] = letter.upper()
                        break
        
        return matched_attributes
    
    def get_covered_attributes(self):
        """Return set of attribute names we have rules for."""
        return set(self.rules.keys())


class CategoryManager:
    """
    Manages category requirements and rule coverage.
    
    - Stores user-defined required attributes per category
    - Tracks which attributes have rules per category
    - Tracks skipped/unlearnable attributes per category
    """
    
    CATEGORY_VERIFY_THRESHOLD = 5  # Verify attributes with 5 HTTP fetches after initial setup
    
    def __init__(self):
        # category_id -> list of required attribute names
        self.category_requirements = {}
        
        # category_id -> set of attributes we have rules for
        self.category_rule_coverage = {}
        
        # category_id -> {name}
        self.category_info = {}
        
        # category_id -> set of attributes that are skipped/unlearnable
        # (user decided to skip, counts as "covered" for completeness)
        self.category_skipped_attributes = {}

        # category_id -> set of attributes that are un-teachable and should ALWAYS be fetched from API
        # (counts as "handled" for completeness, but forces HTTP even if other rules match)
        self.category_always_fetch_attributes = {}
        
        # category_id -> count of verification fetches done (after initial requirements set)
        self.category_verify_count = {}
        
        # category_id -> set of all attribute names seen from API during verification
        self.category_known_attributes = {}
    
    def load_from_db(self, stdout=None):
        """Load category requirements from database."""
        requirements_loaded = 0
        
        # Load categories with CeX IDs
        for cat in ProductCategory.objects.filter(cex_category_id__isnull=False):
            self.category_info[cat.cex_category_id] = {'name': cat.name}
        
        # Load category requirements
        for req in CategoryRequirement.objects.select_related('category').all():
            if req.category.cex_category_id:
                cat_id = req.category.cex_category_id
                if cat_id not in self.category_requirements:
                    self.category_requirements[cat_id] = []
                    self.category_skipped_attributes[cat_id] = set()
                    self.category_always_fetch_attributes[cat_id] = set()
                
                if req.is_skipped:
                    self.category_skipped_attributes[cat_id].add(req.attribute_name)
                elif getattr(req, 'always_fetch', False):
                    self.category_requirements[cat_id].append(req.attribute_name)
                    self.category_always_fetch_attributes[cat_id].add(req.attribute_name)
                else:
                    self.category_requirements[cat_id].append(req.attribute_name)
                requirements_loaded += 1
        
        if stdout:
            stdout.write(f'Loaded {requirements_loaded} category requirements from database')
        
        return requirements_loaded
    
    def get_or_create_category(self, cex_category_id, category_name):
        """Get or create a ProductCategory by CeX ID."""
        cat, created = ProductCategory.objects.get_or_create(
            cex_category_id=cex_category_id,
            defaults={'name': category_name}
        )
        if not created and cat.name != category_name:
            cat.name = category_name
            cat.save()
        return cat
    
    def save_requirements_to_db(self, cex_category_id, category_name, required_attrs, skipped_attrs=None, always_fetch_attrs=None, bulk_buffer=None):
        """
        Save category requirements to database (or buffer for bulk save).
        If bulk_buffer is provided, appends to buffer instead of saving immediately.
        """
        cat = self.get_or_create_category(cex_category_id, category_name)
        
        if bulk_buffer is not None:
            # Bulk mode: append to buffer
            # Save required attributes
            for attr_name in required_attrs:
                bulk_buffer.append({
                    'category': cat,
                    'attribute_name': attr_name,
                    'is_skipped': False,
                    'always_fetch': bool(always_fetch_attrs and attr_name in set(always_fetch_attrs)),
                })
            
            # Save skipped attributes
            if skipped_attrs:
                for attr_name in skipped_attrs:
                    bulk_buffer.append({
                        'category': cat,
                        'attribute_name': attr_name,
                        'is_skipped': True,
                        'always_fetch': False,
                    })
        else:
            # Immediate mode: save now
            # Clear existing requirements for this category
            CategoryRequirement.objects.filter(category=cat).delete()
            
            # Save required attributes
            for attr_name in required_attrs:
                CategoryRequirement.objects.create(
                    category=cat,
                    attribute_name=attr_name,
                    is_skipped=False,
                    always_fetch=bool(always_fetch_attrs and attr_name in set(always_fetch_attrs)),
                )
            
            # Save skipped attributes
            if skipped_attrs:
                for attr_name in skipped_attrs:
                    CategoryRequirement.objects.create(
                        category=cat,
                        attribute_name=attr_name,
                        is_skipped=True,
                        always_fetch=False,
                    )
    
    def register_category(self, category_id, category_name):
        """Register a category (initialize tracking if new)."""
        if category_id not in self.category_info:
            self.category_info[category_id] = {'name': category_name}
    
    def set_requirements(self, category_id, required_attributes):
        """Set required attributes for a category."""
        self.category_requirements[category_id] = required_attributes
        if category_id not in self.category_rule_coverage:
            self.category_rule_coverage[category_id] = set()
    
    def get_requirements(self, category_id):
        """Get required attributes for a category, or None if not set."""
        return self.category_requirements.get(category_id)
    
    def mark_attribute_covered(self, category_id, attribute_name):
        """Mark that we have a rule for this attribute in this category."""
        if category_id not in self.category_rule_coverage:
            self.category_rule_coverage[category_id] = set()
        self.category_rule_coverage[category_id].add(attribute_name)
    
    def mark_attribute_skipped(self, category_id, attribute_name, save_to_db=True):
        """Mark that this attribute is skipped/unlearnable for this category."""
        if category_id not in self.category_skipped_attributes:
            self.category_skipped_attributes[category_id] = set()
        self.category_skipped_attributes[category_id].add(attribute_name)
        
        # Save to database
        if save_to_db:
            category_name = self.category_info.get(category_id, {}).get('name', 'Unknown')
            cat = self.get_or_create_category(category_id, category_name)
            CategoryRequirement.objects.update_or_create(
                category=cat,
                attribute_name=attribute_name,
                defaults={'is_skipped': True, 'always_fetch': False}
            )

    def mark_attribute_always_fetch(self, category_id, attribute_name, save_to_db=True):
        """Mark that this attribute should always be fetched from API for this category."""
        if category_id not in self.category_always_fetch_attributes:
            self.category_always_fetch_attributes[category_id] = set()
        self.category_always_fetch_attributes[category_id].add(attribute_name)

        # Ensure it's still listed as a requirement (but not "rule-match required")
        if category_id not in self.category_requirements:
            self.category_requirements[category_id] = []
        if attribute_name not in self.category_requirements[category_id]:
            self.category_requirements[category_id].append(attribute_name)

        # Save to database
        if save_to_db:
            category_name = self.category_info.get(category_id, {}).get('name', 'Unknown')
            cat = self.get_or_create_category(category_id, category_name)
            CategoryRequirement.objects.update_or_create(
                category=cat,
                attribute_name=attribute_name,
                defaults={'is_skipped': False, 'always_fetch': True}
            )

    def is_attribute_always_fetch(self, category_id, attribute_name):
        """Check if attribute is marked as always-fetch for this category."""
        return attribute_name in self.category_always_fetch_attributes.get(category_id, set())

    def get_always_fetch_attributes(self, category_id):
        """Get always-fetch attributes for this category."""
        return self.category_always_fetch_attributes.get(category_id, set())
    
    def is_attribute_skipped(self, category_id, attribute_name):
        """Check if attribute is skipped for this category."""
        return attribute_name in self.category_skipped_attributes.get(category_id, set())
    
    def is_category_in_verification(self, category_id):
        """
        Check if category is still in verification phase.
        Returns True if we haven't done enough verification fetches yet.
        """
        if category_id not in self.category_verify_count:
            return False  # Never started verification (requirements not set yet)
        return self.category_verify_count[category_id] < self.CATEGORY_VERIFY_THRESHOLD
    
    def is_category_verified(self, category_id):
        """Check if category has completed verification phase."""
        return self.category_verify_count.get(category_id, 0) >= self.CATEGORY_VERIFY_THRESHOLD
    
    def start_verification(self, category_id, initial_attributes):
        """Start verification phase for a category with its initial attribute set."""
        self.category_verify_count[category_id] = 0
        self.category_known_attributes[category_id] = set(initial_attributes)
    
    def increment_verify_count(self, category_id):
        """Increment the verification fetch count for a category."""
        self.category_verify_count[category_id] = self.category_verify_count.get(category_id, 0) + 1
    
    def get_verify_count(self, category_id):
        """Get current verification count."""
        return self.category_verify_count.get(category_id, 0)
    
    def get_new_attributes(self, category_id, api_attributes):
        """
        Compare API attributes against known attributes for this category.
        Returns set of NEW attributes not seen before.
        """
        known = self.category_known_attributes.get(category_id, set())
        return set(api_attributes) - known
    
    def add_known_attributes(self, category_id, attributes):
        """Add attributes to the known set for a category."""
        if category_id not in self.category_known_attributes:
            self.category_known_attributes[category_id] = set()
        self.category_known_attributes[category_id].update(attributes)
    
    def get_missing_attributes(self, category_id):
        """
        Get list of required attributes we don't have rules for yet.
        Excludes skipped attributes (they count as handled).
        Returns:
          - None if requirements have not been configured for this category yet
          - [] if requirements are configured and all are covered (or none required)
          - [attr, ...] list of missing required attributes otherwise
        """
        requirements = self.category_requirements.get(category_id, None)
        if requirements is None:
            return None
        if requirements == []:
            return []
        
        covered = self.category_rule_coverage.get(category_id, set())
        skipped = self.category_skipped_attributes.get(category_id, set())
        always_fetch = self.category_always_fetch_attributes.get(category_id, set())
        # Always-fetch attributes count as "handled" (but force HTTP), so they are not "missing"
        return [attr for attr in requirements if attr not in covered and attr not in skipped and attr not in always_fetch]
    
    def is_category_complete(self, category_id):
        """Check if we have rules (or skipped) for all required attributes."""
        missing = self.get_missing_attributes(category_id)
        if missing is None:
            return False
        return len(missing) == 0


class Command(BaseCommand):
    help = 'Process variants with category-aware rule-based attribute matching'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/118.0.5993.117 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://www.cex.uk/",
        }
        self.interactive = False
        self.results = []  # Track results for each SKU
        self.unlearnable_details = []  # Detailed log of unlearnable attributes
        
        # Bulk save buffers
        self.rules_to_save = []  # Accumulate rules for bulk save
        self.requirements_to_save = []  # Accumulate requirements for bulk save

    def add_arguments(self, parser):
        parser.add_argument(
            '--interactive',
            action='store_true',
            help='Enable interactive prompts for manual rule definition when auto-learning fails',
        )
    
    def bulk_save_to_db(self, engine, category_mgr, category_id=None):
        """
        Bulk save all accumulated rules and requirements to database.
        Much faster than individual saves.
        """
        # Bulk save match rules
        if self.rules_to_save:
            self.stdout.write(f'  Bulk saving {len(self.rules_to_save)} match rules...')
            
            # Check which rules don't exist yet (avoid duplicates)
            rules_to_create = []
            for rule_data in self.rules_to_save:
                exists = MatchRule.objects.filter(
                    attribute_name=rule_data['attribute_name'],
                    attribute_value=rule_data['attribute_value'],
                    match_pattern=rule_data['match_pattern']
                ).exists()
                
                if not exists:
                    rules_to_create.append(MatchRule(
                        attribute_name=rule_data['attribute_name'],
                        attribute_value=rule_data['attribute_value'],
                        match_pattern=rule_data['match_pattern'],
                        source_sku=rule_data['source_sku'],
                        source_title=rule_data['source_title']
                    ))
            
            if rules_to_create:
                MatchRule.objects.bulk_create(rules_to_create, ignore_conflicts=True)
                self.stdout.write(f'  ✓ Saved {len(rules_to_create)} new rules to database')
            
            self.rules_to_save.clear()
        
        # Bulk save category requirements (including any skipped/always_fetch that were added during processing)
        if category_id and category_id in category_mgr.category_info:
            category_name = category_mgr.category_info[category_id]['name']
            required_attrs = category_mgr.get_requirements(category_id) or []
            skipped_attrs = list(category_mgr.category_skipped_attributes.get(category_id, set()))
            always_fetch_attrs = list(category_mgr.category_always_fetch_attributes.get(category_id, set()))
            
            # Use immediate mode to save final state (not bulk buffer)
            category_mgr.save_requirements_to_db(
                category_id, category_name, required_attrs,
                skipped_attrs=skipped_attrs,
                always_fetch_attrs=always_fetch_attrs,
                bulk_buffer=None  # Immediate save
            )
            self.stdout.write(f'  ✓ Saved category requirements to database')
        
        # Also save any buffered requirements
        if self.requirements_to_save:
            self.stdout.write(f'  Bulk saving {len(self.requirements_to_save)} buffered requirements...')
            
            # Group by category for efficient deletion
            categories_to_clear = set(req['category'] for req in self.requirements_to_save)
            for cat in categories_to_clear:
                CategoryRequirement.objects.filter(category=cat).delete()
            
            # Bulk create all requirements
            requirements_to_create = [
                CategoryRequirement(
                    category=req['category'],
                    attribute_name=req['attribute_name'],
                    is_skipped=req['is_skipped'],
                    always_fetch=req['always_fetch']
                )
                for req in self.requirements_to_save
            ]
            
            CategoryRequirement.objects.bulk_create(requirements_to_create)
            self.stdout.write(f'  ✓ Saved {len(requirements_to_create)} buffered requirements to database')
            
            self.requirements_to_save.clear()
    
    def prompt_for_listings_file(self):
        """Prompt user for listings.json file path."""
        self.stdout.write('\n' + '='*60)
        self.stdout.write('CATEGORY PROCESSING SETUP')
        self.stdout.write('='*60)
        self.stdout.write('')
        self.stdout.write('Enter the path to the listings.json file for this category:')
        self.stdout.write('  (File should contain a "listings" array with items having "id" and "title" fields)')
        self.stdout.write('')
        
        while True:
            file_path = input('  Listings file path: ').strip()
            if not file_path:
                self.stdout.write(self.style.ERROR('  Path cannot be empty'))
                continue
            
            # Expand user home directory if ~ is used
            file_path = os.path.expanduser(file_path)
            file_path = Path(file_path)
            
            if not file_path.exists():
                self.stdout.write(self.style.ERROR(f'  File not found: {file_path}'))
                continue
            
            if not file_path.is_file():
                self.stdout.write(self.style.ERROR(f'  Path is not a file: {file_path}'))
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'listings' not in data:
                    self.stdout.write(self.style.ERROR('  File does not contain "listings" key'))
                    continue
                
                listings = data['listings']
                if not isinstance(listings, list):
                    self.stdout.write(self.style.ERROR('  "listings" must be an array'))
                    continue
                
                if len(listings) == 0:
                    self.stdout.write(self.style.ERROR('  Listings array is empty'))
                    continue
                
                # Validate structure
                sample = listings[0]
                if 'id' not in sample or 'title' not in sample:
                    self.stdout.write(self.style.ERROR('  Listings must have "id" and "title" fields'))
                    continue
                
                self.stdout.write(self.style.SUCCESS(f'  ✓ Loaded {len(listings)} listings from {file_path}'))
                return file_path, listings
                
            except json.JSONDecodeError as e:
                self.stdout.write(self.style.ERROR(f'  Invalid JSON: {e}'))
                continue
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Error reading file: {e}'))
                continue
    
    def prompt_for_filter_file(self, engine):
        """Prompt user for filter file path, with suggestions."""
        self.stdout.write('')
        self.stdout.write('Enter the path to the filter file for this category:')
        self.stdout.write('  (File should be a CEX_*.json filter file)')
        self.stdout.write('')
        
        # Show available filter files as suggestions
        if engine.FILTERS_DIR.exists():
            filter_files = list(engine.FILTERS_DIR.glob('CEX_*.json'))
            if filter_files:
                self.stdout.write('  Available filter files:')
                for i, f in enumerate(filter_files[:10], 1):  # Show first 10
                    self.stdout.write(f'    {i}. {f.name}')
                if len(filter_files) > 10:
                    self.stdout.write(f'    ... and {len(filter_files) - 10} more')
                self.stdout.write('')
        
        while True:
            file_path = input('  Filter file path (or number from list above): ').strip()
            if not file_path:
                self.stdout.write(self.style.ERROR('  Path cannot be empty'))
                continue
            
            # Check if user entered a number (from suggestions)
            if file_path.isdigit() and engine.FILTERS_DIR.exists():
                filter_files = list(engine.FILTERS_DIR.glob('CEX_*.json'))
                idx = int(file_path) - 1
                if 0 <= idx < len(filter_files):
                    file_path = str(filter_files[idx])
                    self.stdout.write(f'  Using: {file_path}')
            
            # Expand user home directory if ~ is used
            file_path = os.path.expanduser(file_path)
            file_path = Path(file_path)
            
            if not file_path.exists():
                self.stdout.write(self.style.ERROR(f'  File not found: {file_path}'))
                continue
            
            if not file_path.is_file():
                self.stdout.write(self.style.ERROR(f'  Path is not a file: {file_path}'))
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Extract category name from filename: CEX_Xbox_One_Consoles.json -> Xbox One Consoles
                category_name = file_path.stem.replace('CEX_', '').replace('_', ' ')
                
                self.stdout.write(self.style.SUCCESS(f'  ✓ Loaded filter file: {file_path}'))
                self.stdout.write(f'  Category name: {category_name}')
                return file_path, category_name, data
                
            except json.JSONDecodeError as e:
                self.stdout.write(self.style.ERROR(f'  Invalid JSON: {e}'))
                continue
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  Error reading file: {e}'))
                continue
    
    def prompt_for_requirements(self, category_id, category_name, available_attributes, category_mgr):
        """
        Prompt user to select required attributes for a category.
        Shows previously used requirements as default option.
        In non-interactive mode, auto-selects ALL attributes.
        """
        # AUTO MODE: Use all attributes without prompting
        if not self.interactive:
            attr_list = list(available_attributes)
            self.stdout.write(f'\n  AUTO MODE: Using all {len(attr_list)} attributes for "{category_name}"')
            self.stdout.write(f'  Attributes: {attr_list}')
            return attr_list
        
        # INTERACTIVE MODE: Prompt user
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.WARNING(f'NEW CATEGORY DISCOVERED: {category_name} (ID: {category_id})'))
        
        # Find previously used requirements from other categories
        previous_requirements = set()
        for cat_id, requirements in category_mgr.category_requirements.items():
            previous_requirements.update(requirements)
        
        # Filter to only attributes available in this category
        attr_list = list(available_attributes)
        reusable = [attr for attr in previous_requirements if attr in attr_list]
        
        self.stdout.write('Available attributes:')
        for i, attr in enumerate(attr_list, 1):
            marker = ' *' if attr in reusable else ''
            self.stdout.write(f'  {i}. {attr}{marker}')
        
        self.stdout.write('')
        
        if reusable:
            self.stdout.write(f'Previously used (* marked): {reusable}')
            self.stdout.write('')
            self.stdout.write('Options:')
            self.stdout.write('  [Enter] = Use previous selection')
            self.stdout.write('  [+3,5] = Add to previous (e.g., +3,5 adds items 3 and 5)')
            self.stdout.write('  [-3,5] = Remove from previous (e.g., -3,5 removes items 3 and 5)')
            self.stdout.write('  [1,2,3] = New selection (numbers only)')
            self.stdout.write('  [all] = All attributes')
            self.stdout.write('  [none] = No requirements')
        else:
            self.stdout.write('Options:')
            self.stdout.write('  [1,2,3] = Select by number')
            self.stdout.write('  [all] = All attributes')
            self.stdout.write('  [none] = No requirements')
        
        user_input = input('> ').strip()
        
        # Handle different input types
        if user_input == '' and reusable:
            # Use previous selection
            selected = reusable
        elif user_input.startswith('+') and reusable:
            # Add to previous selection
            try:
                additional = user_input[1:]
                indices = [int(x.strip()) for x in additional.split(',') if x.strip()]
                additional_attrs = [attr_list[i-1] for i in indices if 1 <= i <= len(attr_list)]
                selected = list(set(reusable + additional_attrs))
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('Invalid input, using previous selection'))
                selected = reusable
        elif user_input.startswith('-') and reusable:
            # Remove from previous selection
            try:
                to_remove = user_input[1:]
                indices = [int(x.strip()) for x in to_remove.split(',') if x.strip()]
                remove_attrs = [attr_list[i-1] for i in indices if 1 <= i <= len(attr_list)]
                selected = [attr for attr in reusable if attr not in remove_attrs]
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('Invalid input, using previous selection'))
                selected = reusable
        elif user_input.lower() == 'all':
            selected = attr_list
        elif user_input.lower() == 'none' or user_input == '':
            selected = []
        else:
            try:
                indices = [int(x.strip()) for x in user_input.split(',') if x.strip()]
                selected = [attr_list[i-1] for i in indices if 1 <= i <= len(attr_list)]
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('Invalid input, defaulting to previous or none'))
                selected = reusable if reusable else []
        
        self.stdout.write(self.style.SUCCESS(f'Selected: {selected}'))
        self.stdout.write('='*60 + '\n')
        
        return selected
    
    def fetch_sku_details(self, sku):
        """Fetch SKU details from CeX API."""
        api_url = f'https://wss2.cex.uk.webuy.io/v3/boxes/{sku}/detail'
        try:
            response = requests.get(api_url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f'  HTTP Error: {str(e)}'))
            return None
    
    def prompt_for_unlearnable_rule(self, sku_title, attr_name, attr_value, category_name):
        """
        Prompt ONCE when an attribute can't be auto-learned for a category.
        Returns: match_rule (str or list) if user defines one, 'SKIP' to skip, or 'ALWAYS_FETCH' for API-only.
        """
        title_lower = sku_title.lower()
        words = re.findall(r'\b\w+\b', title_lower)
        first_word = words[0] if words else ''
        first_word_valid = len(first_word) >= 2
        grade_or_condition = AttributeMatchRuleEngine().is_grade_or_condition_attribute(attr_name)
        
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'  ⚠ Cannot auto-learn: {attr_name}={attr_value}'))
        self.stdout.write(f'  Category: {category_name}')
        self.stdout.write(f'  Title: {sku_title}')
        self.stdout.write(f'  Title words: {", ".join(words[:8])}{"..." if len(words) > 8 else ""}')
        self.stdout.write('')
        self.stdout.write('  Options:')
        if first_word_valid:
            self.stdout.write(f'    [1]         Use first word: "{first_word}"')
        else:
            self.stdout.write(f'    [1]         (unavailable - "{first_word}" too short)')
        self.stdout.write('    [Enter/s]   Skip this attribute for this category')
        self.stdout.write('    [a]         Always fetch this attribute from API for this category (un-teachable)')
        self.stdout.write('    [word]      Type a match rule (min 2 chars)')
        if grade_or_condition:
            self.stdout.write('               (for grade/condition you can enter a single letter like "B")')
        self.stdout.write('    [w1,w2]     Multiple words (ALL must appear)')
        self.stdout.write('')
        
        user_input = input('  > ').strip()
        
        # Enter or 's' = skip (safe default)
        if user_input == '' or user_input.lower() == 's' or user_input.lower() == 'skip':
            return 'SKIP'

        # 'a' = always fetch from API for this attribute/category
        if user_input.lower() == 'a':
            return 'ALWAYS_FETCH'
        
        # '1' = use first word
        if user_input == '1':
            if first_word_valid:
                self.stdout.write(f'  Using: "{first_word}"')
                return first_word
            else:
                self.stdout.write(self.style.ERROR(f'  First word "{first_word}" too short. Skipping.'))
                return 'SKIP'
        
        # Check if comma-separated list
        if ',' in user_input:
            words_list = [w.strip().lower() for w in user_input.split(',') if w.strip()]
            if len(words_list) >= 2 and all(len(w) >= 2 for w in words_list):
                self.stdout.write(f'  Using array: {words_list} (ALL must match)')
                return words_list
            else:
                self.stdout.write(self.style.ERROR('  Invalid array (need 2+ words, each 2+ chars). Using as single string.'))
                user_input = user_input.replace(',', ' ').strip()
        
        # Single string
        match_rule = user_input.lower()
        if len(match_rule) >= 2:
            self.stdout.write(f'  Using: "{match_rule}"')
            return match_rule
        if grade_or_condition and len(match_rule) == 1:
            # Store as regex rule to keep global min length at 2 for normal string rules
            self.stdout.write(f'  Using single-letter grade/condition via regex: "{match_rule}"')
            return {'regex': r'\b' + re.escape(match_rule) + r'\b'}
        else:
            self.stdout.write(self.style.ERROR('  Too short (min 2 chars). Skipping attribute.'))
            return 'SKIP'

    def save_results_incremental(self, output_file, engine, category_mgr, http_requests, rule_matches):
        """Save results to file incrementally after each SKU."""
        unlearnable_count = sum(len(r.get('unlearnable', [])) for r in self.results)
        
        output_data = {
            'summary': {
                'total_processed': len(self.results),
                'http_requests': http_requests,
                'rule_matches': rule_matches,
                'rules_learned': sum(len(r) for r in engine.rules.values()),
                'unlearnable_count': unlearnable_count,
                'unlearnable_details_count': len(self.unlearnable_details)
            },
            'processed_skus': [r['sku'] for r in self.results],  # For resume support
            'categories': {
                str(cat_id): {
                    'name': info['name'],
                    'requirements': category_mgr.get_requirements(cat_id) or [],
                    'covered': list(category_mgr.category_rule_coverage.get(cat_id, set())),
                    'skipped': list(category_mgr.category_skipped_attributes.get(cat_id, set())),
                    'always_fetch': list(category_mgr.category_always_fetch_attributes.get(cat_id, set())),
                    'complete': category_mgr.is_category_complete(cat_id)
                }
                for cat_id, info in category_mgr.category_info.items()
            },
            'rules': engine.rules,
            'results': self.results
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        # Also save unlearnable details to separate file
        if self.unlearnable_details:
            unlearnable_file = output_file.replace('.json', '_unlearnable_details.json')
            unlearnable_data = {
                'summary': {
                    'total_unlearnable': len(self.unlearnable_details),
                    'unique_attributes': len(set(d['attribute_name'] for d in self.unlearnable_details)),
                    'unique_skus': len(set(d['sku'] for d in self.unlearnable_details))
                },
                'unlearnable': self.unlearnable_details
            }
            with open(unlearnable_file, 'w', encoding='utf-8') as f:
                json.dump(unlearnable_data, f, indent=2, ensure_ascii=False)
    
    def load_previous_results(self, output_file):
        """Load previous results for resume support. Returns set of processed SKUs."""
        if not os.path.exists(output_file):
            return None, set()
        
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            processed_skus = set(data.get('processed_skus', []))
            results = data.get('results', [])
            return results, processed_skus
        except (json.JSONDecodeError, IOError):
            return None, set()
    
    def prompt_for_new_attributes(self, category_id, category_name, new_attrs, category_mgr):
        """
        Prompt user when new attributes are discovered during verification phase.
        Returns list of attributes user wants to add to requirements.
        In non-interactive mode, auto-adds ALL new attributes.
        """
        new_attrs_list = list(new_attrs)
        
        # AUTO MODE: Add all new attributes without prompting
        if not self.interactive:
            self.stdout.write(f'  AUTO MODE: Adding {len(new_attrs_list)} new attributes: {new_attrs_list}')
            return new_attrs_list
        
        # INTERACTIVE MODE: Prompt user
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'  ⚠ NEW ATTRIBUTES DISCOVERED for "{category_name}"!'))
        self.stdout.write(f'  Current requirements: {category_mgr.get_requirements(category_id)}')
        self.stdout.write('')
        self.stdout.write('  New attributes found:')
        
        for i, attr in enumerate(new_attrs_list, 1):
            self.stdout.write(f'    {i}. {attr}')
        
        self.stdout.write('')
        self.stdout.write('  Options:')
        self.stdout.write('    [Enter]     Skip all (don\'t add any)')
        self.stdout.write('    [all]       Add all new attributes')
        self.stdout.write('    [1,2,3]     Add specific ones by number')
        self.stdout.write('')
        
        user_input = input('  > ').strip()
        
        if user_input == '' or user_input.lower() == 'none':
            self.stdout.write('  Skipped all new attributes.')
            return []
        elif user_input.lower() == 'all':
            self.stdout.write(f'  Adding all: {new_attrs_list}')
            return new_attrs_list
        else:
            try:
                indices = [int(x.strip()) for x in user_input.split(',') if x.strip()]
                selected = [new_attrs_list[i-1] for i in indices if 1 <= i <= len(new_attrs_list)]
                self.stdout.write(f'  Adding: {selected}')
                return selected
            except (ValueError, IndexError):
                self.stdout.write(self.style.ERROR('  Invalid input, skipping all.'))
                return []
    
    def prompt_for_missing_api_attribute(self, attr_name, category_name, sku_title):
        """
        Prompt user when a required attribute is not in the API response.
        Returns:
          - 'skip' to skip this attribute
          - 'keep' to keep it required
          - (value_string) if user manually defines the value
        """
        # AUTO MODE: Just skip
        if not self.interactive:
            return 'skip'
        
        # INTERACTIVE MODE: Prompt user
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'  ⚠ Required attribute "{attr_name}" not found in API response!'))
        self.stdout.write(f'  Category: {category_name}')
        self.stdout.write(f'  SKU Title: {sku_title}')
        self.stdout.write('')
        self.stdout.write('  This attribute will never be learnable for this category.')
        self.stdout.write('  Options:')
        self.stdout.write('    [Enter/s]   Skip this attribute (mark as skipped)')
        self.stdout.write('    [k]         Keep it required (will cause repeated HTTP)')
        self.stdout.write('    [m]         Manually define value for this SKU')
        self.stdout.write('')
        
        user_input = input('  > ').strip().lower()
        
        if user_input == 'k':
            return 'keep'
        elif user_input == 'm':
            # Prompt for manual value
            self.stdout.write('')
            self.stdout.write(f'  Enter value for "{attr_name}":')
            manual_value = input('  > ').strip()
            if manual_value:
                self.stdout.write(f'  Using manual value: "{manual_value}"')
                return manual_value
            else:
                self.stdout.write(self.style.ERROR('  Empty value, skipping attribute'))
                return 'skip'
        else:
            # Enter or 's' = skip
            return 'skip'
    
    def log_unlearnable_detail(self, sku, sku_title, attr_name, attr_value, reason, engine):
        """
        Log detailed information about why an attribute couldn't be learned.
        Captures all the data needed for manual review later.
        """
        # Tokenize title and attribute value to show what we tried
        title_tokens = list(engine.tokenize_words(sku_title))
        label_tokens = list(engine.tokenize_words(str(attr_value))) if attr_value else []
        
        # Find what candidates were found
        title_token_set = engine.tokenize_words(sku_title)
        label_token_set = engine.tokenize_words(str(attr_value)) if attr_value else set()
        candidates = list(engine.find_candidate_matches(title_token_set, label_token_set))
        
        # Check if any existing rules exist for this attribute
        existing_rules = []
        if attr_name in engine.rules:
            for rule in engine.rules[attr_name]:
                existing_rules.append({
                    'value': rule['value'],
                    'match_rule': rule['match_rule'],
                    'source_sku': rule.get('source_sku', '')
                })
        
        detail = {
            'sku': sku,
            'title': sku_title,
            'attribute_name': attr_name,
            'expected_value': attr_value,
            'reason': reason,
            'title_tokens': sorted(title_tokens[:30]),  # Limit for readability
            'value_tokens': sorted(label_tokens),
            'candidate_matches': sorted(candidates),
            'existing_rules_for_attribute': existing_rules,
            'suggestions': []
        }
        
        # Add suggestions based on analysis
        if not candidates:
            detail['suggestions'].append('No common tokens found between title and value - value may not appear in title')
        elif candidates:
            valid_candidates = [c for c in candidates if len(c) >= 2]
            if valid_candidates:
                detail['suggestions'].append(f'Try manual rule with: {valid_candidates[0]}')
        
        # Check for partial matches
        value_lower = str(attr_value).lower() if attr_value else ''
        title_lower = sku_title.lower()
        if value_lower in title_lower:
            detail['suggestions'].append(f'Value "{value_lower}" appears as substring in title - may need exact match rule')
        
        self.unlearnable_details.append(detail)
    
    def process_single_sku(self, sku, sku_title, category_id, category_name, engine, category_mgr, http_requests, rule_matches, output_file, processed_skus):
        """
        Process a single SKU: try rules first, then HTTP if needed.
        Returns updated (http_requests, rule_matches) tuple.
        """
        # Skip if already processed
        if sku in processed_skus:
            return http_requests, rule_matches
        
        # Initialize result entry
        sku_result = {
            'sku': sku,
            'title': sku_title,
            'category': category_name,
            'source': None,
            'attributes': {},
            'unlearnable': []
        }
        
        def _is_software_category(name: str) -> bool:
            return bool(name) and ('software' in str(name).lower())
        
        # Skip Software categories
        if _is_software_category(category_name):
            sku_result['source'] = 'skipped_software_category'
            self.results.append(sku_result)
            self.save_results_incremental(output_file, engine, category_mgr, http_requests, rule_matches)
            return http_requests, rule_matches
        
        # Check if category is in verification phase or has always-fetch attributes
        force_http = False
        if category_mgr.is_category_in_verification(category_id):
            verify_count = category_mgr.get_verify_count(category_id)
            remaining = category_mgr.CATEGORY_VERIFY_THRESHOLD - verify_count
            self.stdout.write(f'  Category in VERIFICATION phase ({remaining} fetches remaining)')
            force_http = True
        
        always_fetch_attrs = category_mgr.get_always_fetch_attributes(category_id)
        if always_fetch_attrs:
            force_http = True
            self.stdout.write(f'  Forced HTTP: always-fetch attributes: {sorted(list(always_fetch_attrs))}')
        
        # Try to match rules for ALL attributes (including unlearnable - they might have filter file rules)
        required_attrs = category_mgr.get_requirements(category_id)
        if required_attrs is not None and not force_http:
            always_fetch_set = category_mgr.get_always_fetch_attributes(category_id)
            skipped_set = category_mgr.category_skipped_attributes.get(category_id, set())  # unlearnable
            
            # Try to match ALL attributes
            matched_attrs = engine.apply_rules_to_sku(sku_title, required_attrs)
            
            # Check which learnable attributes are missing (unlearnable = leave empty, don't fetch API)
            learnable_attrs = [a for a in required_attrs if a not in always_fetch_set and a not in skipped_set]
            learnable_missing = [a for a in learnable_attrs if a not in matched_attrs]
            unlearnable_missing = [a for a in required_attrs if a in skipped_set and a not in matched_attrs]
            
            if not learnable_missing:
                # All learnable attributes matched! (unlearnable ones we leave empty)
                rule_matches += 1
                sku_result['source'] = 'rule_match'
                sku_result['attributes'] = matched_attrs
                if unlearnable_missing:
                    self.stdout.write(f'  Unlearnable (empty): {unlearnable_missing}')
                self.results.append(sku_result)
                self.save_results_incremental(output_file, engine, category_mgr, http_requests, rule_matches)
                self.stdout.write(self.style.SUCCESS(f'  RULE MATCH: {json.dumps(matched_attrs)}'))
                return http_requests, rule_matches
            else:
                # Some learnable attributes missing - need HTTP to try learning
                self.stdout.write(f'  Missing (need HTTP to learn): {learnable_missing}')
                if unlearnable_missing:
                    self.stdout.write(f'  Also missing (unlearnable, will skip): {unlearnable_missing}')
        
        # Need HTTP request
        self.stdout.write(f'  Fetching from API...')
        http_requests += 1
        sku_result['source'] = 'http'
        
        result = self.fetch_sku_details(sku)
        if not result:
            self.results.append(sku_result)
            self.save_results_incremental(output_file, engine, category_mgr, http_requests, rule_matches)
            return http_requests, rule_matches
        
        box_details = result.get('response', {}).get('data', {}).get('boxDetails', [])
        if not box_details:
            self.stdout.write(self.style.WARNING('  No box details in response'))
            self.results.append(sku_result)
            self.save_results_incremental(output_file, engine, category_mgr, http_requests, rule_matches)
            return http_requests, rule_matches
        
        box = box_details[0]
        api_category_id = box.get('categoryId')
        api_category_name = box.get('categoryName', 'Unknown')
        attribute_info = box.get('attributeInfo', []) or []
        
        # Verify category matches
        if api_category_id != category_id:
            self.stdout.write(self.style.WARNING(f'  Category mismatch! Expected {category_id} ({category_name}), got {api_category_id} ({api_category_name})'))
        
        # Register friendly name mappings
        for attr in attribute_info:
            attr_name = attr.get('attributeName', '')
            friendly_name = attr.get('attributeFriendlyName', '')
            if attr_name and friendly_name:
                engine.register_friendly_name_mapping(friendly_name, attr_name)
        
        # Handle new category requirements setup
        if category_mgr.get_requirements(category_id) is None:
            if attribute_info:
                available_attrs = [attr.get('attributeName', '') for attr in attribute_info if attr.get('attributeName')]
                required = self.prompt_for_requirements(category_id, category_name, available_attrs, category_mgr)
                category_mgr.set_requirements(category_id, required)
                category_mgr.start_verification(category_id, available_attrs)
                category_mgr.save_requirements_to_db(category_id, category_name, required, bulk_buffer=self.requirements_to_save)
                engine.pregenerate_rules_for_category(category_name, stdout=self.stdout, bulk_buffer=self.rules_to_save)
                for attr_name in required:
                    if attr_name in engine.rules and len(engine.rules[attr_name]) > 0:
                        category_mgr.mark_attribute_covered(category_id, attr_name)
            else:
                category_mgr.set_requirements(category_id, [])
                category_mgr.start_verification(category_id, set())
        
        required_attrs = category_mgr.get_requirements(category_id) or []
        always_fetch_attrs = category_mgr.get_always_fetch_attributes(category_id)
        
        if not attribute_info:
            self.stdout.write('  No attribute info in response')
            if category_mgr.is_category_in_verification(category_id):
                category_mgr.increment_verify_count(category_id)
            self.results.append(sku_result)
            self.save_results_incremental(output_file, engine, category_mgr, http_requests, rule_matches)
            return http_requests, rule_matches
        
        # Handle verification phase
        api_attr_names = {attr.get('attributeName', '') for attr in attribute_info if attr.get('attributeName')}
        if category_mgr.is_category_in_verification(category_id):
            new_attrs = category_mgr.get_new_attributes(category_id, api_attr_names)
            if new_attrs:
                self.stdout.write(self.style.WARNING(f'  New attributes: {list(new_attrs)}'))
                # prompt_for_new_attributes handles both interactive and auto mode
                to_add = self.prompt_for_new_attributes(category_id, category_name, new_attrs, category_mgr)
                if to_add:
                    current_reqs = category_mgr.get_requirements(category_id) or []
                    updated_reqs = current_reqs + to_add
                    category_mgr.set_requirements(category_id, updated_reqs)
                    category_mgr.save_requirements_to_db(
                        category_id, category_name, updated_reqs,
                        skipped_attrs=list(category_mgr.category_skipped_attributes.get(category_id, set())),
                        always_fetch_attrs=list(category_mgr.category_always_fetch_attributes.get(category_id, set())),
                        bulk_buffer=self.requirements_to_save
                    )
                    required_attrs = updated_reqs
            category_mgr.add_known_attributes(category_id, api_attr_names)
            category_mgr.increment_verify_count(category_id)
            verify_count = category_mgr.get_verify_count(category_id)
            if category_mgr.is_category_verified(category_id):
                self.stdout.write(self.style.SUCCESS(f'  ✓ VERIFICATION COMPLETE ({verify_count} fetches)'))
            else:
                remaining = category_mgr.CATEGORY_VERIFY_THRESHOLD - verify_count
                self.stdout.write(f'  Verification: {verify_count}/{category_mgr.CATEGORY_VERIFY_THRESHOLD} ({remaining} remaining)')
        
        # Check for missing required attributes - TRY RULES FIRST!
        for req_attr in required_attrs:
            if req_attr not in api_attr_names and not category_mgr.is_attribute_skipped(category_id, req_attr):
                # Try to apply existing rules first before prompting
                matched_attrs = engine.apply_rules_to_sku(sku_title, [req_attr])
                if req_attr in matched_attrs:
                    # Rule matched! Use it
                    sku_result['attributes'][req_attr] = matched_attrs[req_attr]
                    self.stdout.write(f'  RULE MATCH (missing from API): {req_attr}={matched_attrs[req_attr]}')
                    continue
                
                # Attribute not in API - can't learn from it, but maybe filter file has a rule
                self.log_unlearnable_detail(
                    sku, sku_title, req_attr, None,
                    reason='Required attribute not in API response - cannot learn rule',
                    engine=engine
                )
                
                if self.interactive:
                    result = self.prompt_for_missing_api_attribute(req_attr, category_name, sku_title)
                    if result == 'skip':
                        # Mark as unlearnable (not in API, can't ever learn from it)
                        category_mgr.mark_attribute_skipped(category_id, req_attr, save_to_db=False)
                        self.stdout.write(f'  UNLEARNABLE: {req_attr} (not in API, will use filter rules only)')
                    elif result != 'keep':
                        sku_result['attributes'][req_attr] = result
                else:
                    # AUTO MODE: Mark as unlearnable (not in API, can't learn)
                    # Future SKUs: try filter file rules, leave empty if no match
                    category_mgr.mark_attribute_skipped(category_id, req_attr, save_to_db=False)
                    self.stdout.write(f'  UNLEARNABLE: {req_attr} (not in API - future: try filter rules, leave empty if no match)')
        
        # Learn rules for required attributes
        for attr in attribute_info:
            attr_name = attr.get('attributeName', '')
            attr_values = attr.get('attributeValue', [])
            if not attr_name or not attr_values or attr_name not in required_attrs:
                continue
            
            attr_value = attr_values[0] if isinstance(attr_values, list) else str(attr_values)
            sku_result['attributes'][attr_name] = attr_value
            
            if attr_name in always_fetch_attrs:
                continue
            
            if attr_name in engine.rules:
                matched_attrs = engine.apply_rules_to_sku(sku_title, [attr_name])
                if attr_name in matched_attrs and matched_attrs[attr_name] == attr_value:
                    if attr_name not in category_mgr.category_rule_coverage.get(category_id, set()):
                        category_mgr.mark_attribute_covered(category_id, attr_name)
                    continue
            
            if category_mgr.is_attribute_skipped(category_id, attr_name):
                continue
            
            rule = engine.learn_rule_from_sku(sku_title, attr_name, attr_value)
            if not rule:
                # UNLEARNABLE: No token overlap between title and attribute value
                self.log_unlearnable_detail(
                    sku, sku_title, attr_name, attr_value,
                    reason='Auto-learning failed - no matching tokens found between title and attribute value',
                    engine=engine
                )
                
                if self.interactive:
                    user_response = self.prompt_for_unlearnable_rule(sku_title, attr_name, attr_value, category_name)
                    if user_response == 'SKIP':
                        category_mgr.mark_attribute_skipped(category_id, attr_name, save_to_db=False)  # Mark as unlearnable
                    elif user_response == 'ALWAYS_FETCH':
                        category_mgr.mark_attribute_always_fetch(category_id, attr_name, save_to_db=False)
                    elif user_response:
                        rule = {'attribute': attr_name, 'value': attr_value, 'match_rule': user_response}
                else:
                    # AUTO MODE: Mark as UNLEARNABLE (no tokens match, can't extract from title)
                    # Future SKUs: will try rules, but won't fetch API if no rule matches
                    category_mgr.mark_attribute_skipped(category_id, attr_name, save_to_db=False)
                    self.stdout.write(f'  UNLEARNABLE: {attr_name}={attr_value} (no tokens match - future: try rules only, leave empty if no match)')
            
            if rule:
                stored = engine.store_rule(rule, source_sku=sku, source_title=sku_title)
                if stored:
                    engine.save_rule_to_db(rule, source_sku=sku, source_title=sku_title, bulk_buffer=self.rules_to_save)
                category_mgr.mark_attribute_covered(category_id, attr_name)
                if stored:
                    match_rule = rule['match_rule']
                    if isinstance(match_rule, list):
                        self.stdout.write(f'  LEARNED: {attr_name}={attr_value} via {match_rule}')
                    else:
                        self.stdout.write(f'  LEARNED: {attr_name}={attr_value} via "{match_rule}"')
                else:
                    self.stdout.write(f'  REUSED: {attr_name}={attr_value}')
        
        self.results.append(sku_result)
        self.save_results_incremental(output_file, engine, category_mgr, http_requests, rule_matches)
        return http_requests, rule_matches
    
    def handle(self, *args, **options):
        """Main command handler - processes one category at a time"""
        self.interactive = options.get('interactive', False)
        
        engine = AttributeMatchRuleEngine()
        category_mgr = CategoryManager()
        
        # Load existing rules and category config from database
        self.stdout.write('Loading from database...')
        engine.load_rules_from_db(stdout=self.stdout)
        category_mgr.load_from_db(stdout=self.stdout)
        self.stdout.write('')
        
        # Initialize results
        self.results = []
        http_requests = 0
        rule_matches = 0
        processed_skus = set()
        
        # Main loop: process categories one at a time
        while True:
            # Prompt for listings file
            listings_file, listings = self.prompt_for_listings_file()
            
            # Prompt for filter file
            filter_file, category_name, filter_data = self.prompt_for_filter_file(engine)
            
            # Load filter data into engine for this category
            # Extract category name from filter file and load it
            category_name_from_file = filter_file.stem.replace('CEX_', '').replace('_', ' ')
            engine.preloaded_filters[category_name_from_file] = {}
            for friendly_name, attr_data in filter_data.items():
                if friendly_name in engine.SKIP_FILTER_KEYS:
                    continue
                options_list = attr_data.get('options', [])
                if options_list:
                    engine.preloaded_filters[category_name_from_file][friendly_name] = options_list
            
            # Determine output filename from category name
            output_file = f'process_data_{category_name_from_file.replace(" ", "_").lower()}.json'
            
            # Load resume data if exists
            previous_results, processed_skus_for_category = self.load_previous_results(output_file)
            if processed_skus_for_category:
                self.stdout.write(f'\nFound previous results with {len(processed_skus_for_category)} SKUs already processed.')
                self.stdout.write('Options:')
                self.stdout.write('  [c] Continue (skip already-processed SKUs)')
                self.stdout.write('  [r] Restart (reprocess all)')
                choice = input('> ').strip().lower()
                if choice == 'c':
                    self.results = previous_results if previous_results else []
                    processed_skus = processed_skus_for_category
                else:
                    self.results = []
                    processed_skus = set()
            else:
                self.results = []
                processed_skus = set()
            
            self.stdout.write('')
            self.stdout.write('='*60)
            self.stdout.write(f'Processing category: {category_name}')
            self.stdout.write(f'  Listings: {len(listings)}')
            self.stdout.write(f'  Output: {output_file}')
            self.stdout.write('='*60)
            self.stdout.write('')
            
            # Fetch first SKU to get category ID
            if not listings:
                self.stdout.write(self.style.ERROR('No listings to process'))
                continue
            
            first_sku = listings[0]['id']
            self.stdout.write(f'Fetching category info from first SKU: {first_sku}...')
            result = self.fetch_sku_details(first_sku)
            if not result:
                self.stdout.write(self.style.ERROR('Failed to fetch category info'))
                continue
            
            box_details = result.get('response', {}).get('data', {}).get('boxDetails', [])
            if not box_details:
                self.stdout.write(self.style.ERROR('No box details in response'))
                continue
            
            box = box_details[0]
            category_id = box.get('categoryId')
            api_category_name = box.get('categoryName', 'Unknown')
            attribute_info = box.get('attributeInfo', []) or []
            
            # Register category
            category_mgr.register_category(category_id, category_name)
            category_mgr.category_info[category_id] = {'name': category_name}
            
            # Register friendly name mappings from first SKU
            self.stdout.write('Building attribute mappings...')
            for attr in attribute_info:
                attr_name = attr.get('attributeName', '')
                friendly_name = attr.get('attributeFriendlyName', '')
                if attr_name and friendly_name:
                    engine.register_friendly_name_mapping(friendly_name, attr_name)
            
            # Pre-generate rules from filter file NOW (before processing any SKUs)
            self.stdout.write('Pre-generating rules from filter file...')
            rules_generated = engine.pregenerate_rules_for_category(category_name, stdout=self.stdout, bulk_buffer=self.rules_to_save)
            if rules_generated > 0:
                self.stdout.write(self.style.SUCCESS(f'  ✓ Pre-generated {rules_generated} rules from filter file!'))
                self.stdout.write(f'  This will MASSIVELY reduce HTTP requests for subsequent SKUs.')
            
            # Setup requirements if new category
            if category_mgr.get_requirements(category_id) is None:
                if attribute_info:
                    available_attrs = [attr.get('attributeName', '') for attr in attribute_info if attr.get('attributeName')]
                    required = self.prompt_for_requirements(category_id, category_name, available_attrs, category_mgr)
                    category_mgr.set_requirements(category_id, required)
                    category_mgr.start_verification(category_id, available_attrs)
                    category_mgr.save_requirements_to_db(category_id, category_name, required, bulk_buffer=self.requirements_to_save)
                    
                    # Mark attributes as covered if we already have pre-generated rules
                    for attr_name in required:
                        if attr_name in engine.rules and len(engine.rules[attr_name]) > 0:
                            category_mgr.mark_attribute_covered(category_id, attr_name)
                else:
                    category_mgr.set_requirements(category_id, [])
                    category_mgr.start_verification(category_id, set())
            else:
                # Existing category - mark coverage from pre-generated rules
                self.stdout.write('Category already configured, checking rule coverage...')
                required = category_mgr.get_requirements(category_id) or []
                for attr_name in required:
                    if attr_name in engine.rules and len(engine.rules[attr_name]) > 0:
                        category_mgr.mark_attribute_covered(category_id, attr_name)
            
            # Show rule coverage summary before processing
            required = category_mgr.get_requirements(category_id) or []
            covered = category_mgr.category_rule_coverage.get(category_id, set())
            if required:
                coverage_pct = (len(covered) / len(required) * 100) if required else 0
                self.stdout.write(f'\n  📊 Rule Coverage: {len(covered)}/{len(required)} attributes ({coverage_pct:.0f}%)')
                if len(covered) == len(required):
                    self.stdout.write(self.style.SUCCESS(f'  ✓ All required attributes have rules - most SKUs will skip HTTP!'))
                else:
                    missing = [a for a in required if a not in covered]
                    self.stdout.write(f'  Missing rules for: {missing}')
            self.stdout.write('')
            
            # Process all listings
            total = len(listings)
            for idx, listing in enumerate(listings, 1):
                sku = listing['id']
                sku_title = listing.get('title', sku)
                
                self.stdout.write(f'\n[{idx}/{total}] SKU: {sku}')
                self.stdout.write(f'  Title: {sku_title}')
                
                http_requests, rule_matches = self.process_single_sku(
                    sku, sku_title, category_id, category_name,
                    engine, category_mgr, http_requests, rule_matches,
                    output_file, processed_skus
                )
                processed_skus.add(sku)
            
            # Show category completion status
            missing = category_mgr.get_missing_attributes(category_id)
            if missing:
                self.stdout.write(f'\n  Category progress: still need rules for {missing}')
            else:
                self.stdout.write(self.style.SUCCESS(f'\n  Category COMPLETE: all required attributes have rules!'))
            
            # Bulk save all rules and requirements to database
            self.stdout.write('\n💾 Saving to database...')
            self.bulk_save_to_db(engine, category_mgr, category_id=category_id)
            
            # Ask if user wants to process another category
            self.stdout.write('')
            self.stdout.write('Process another category?')
            self.stdout.write('  [y] Yes, process another category')
            self.stdout.write('  [n] No, finish and save results')
            choice = input('> ').strip().lower()
            
            if choice != 'y':
                break
        
        # Final summary and save
        self.stdout.write('\n' + '='*60)
        self.stdout.write('FINAL SUMMARY:')
        self.stdout.write(f'  Total SKUs processed: {len(self.results)}')
        self.stdout.write(f'  HTTP requests: {http_requests}')
        self.stdout.write(f'  Rule matches: {rule_matches}')
        
        total_rules = sum(len(r) for r in engine.rules.values())
        self.stdout.write(f'  Total rules: {total_rules}')
        
        # Unlearnable details summary
        if self.unlearnable_details:
            self.stdout.write(f'\n  ⚠ Unlearnable attributes: {len(self.unlearnable_details)}')
            unique_attrs = len(set(d['attribute_name'] for d in self.unlearnable_details))
            unique_skus = len(set(d['sku'] for d in self.unlearnable_details))
            self.stdout.write(f'    - Unique attributes: {unique_attrs}')
            self.stdout.write(f'    - Affected SKUs: {unique_skus}')
            self.stdout.write(f'    - Detailed log saved to: *_unlearnable_details.json')
        
        self.stdout.write(self.style.SUCCESS(f'\nAll done!'))
