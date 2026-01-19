import logging
import json
import re
import os
from pathlib import Path
import requests
from django.core.management.base import BaseCommand
from pricing.models_v2 import Variant, ConditionGrade

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
    
    def pregenerate_rules_for_category(self, api_category_name, stdout=None):
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
        
        return candidates[0] if candidates else None
    
    def learn_rule_from_sku(self, sku_title, attribute_name, attribute_value):
        """Learn a match rule from a SKU title and attribute label."""
        if not sku_title or not attribute_value:
            return None
        
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
        return False
    
    def apply_rules_to_sku(self, sku_title, required_attributes=None):
        """
        Apply stored match rules to a SKU title.
        If required_attributes is provided, only match those.
        Returns dict of {attribute_name: attribute_value} for matched rules.
        """
        if not sku_title:
            return {}
        
        matched_attributes = {}
        attributes_to_check = required_attributes if required_attributes else self.rules.keys()
        
        for attribute_name in attributes_to_check:
            if attribute_name not in self.rules:
                continue
                
            rules_list = self.rules[attribute_name]
            sorted_rules = sorted(
                rules_list,
                key=lambda r: (
                    0 if isinstance(r['match_rule'], list) else 1,
                    -len(r['match_rule']) if isinstance(r['match_rule'], str) else -sum(len(w) for w in r['match_rule'])
                )
            )
            
            for rule in sorted_rules:
                match_rule = rule['match_rule']
                if match_rule and self.matches_rule(sku_title, match_rule):
                    matched_attributes[attribute_name] = rule['value']
                    break
        
        return matched_attributes
    
    def get_covered_attributes(self):
        """Return set of attribute names we have rules for."""
        return set(self.rules.keys())


class CategoryManager:
    """
    Manages category detection and requirements.
    
    - Maps SKU prefixes to category IDs (dynamic prefix length)
    - Stores user-defined required attributes per category
    - Tracks which attributes have rules per category
    - Tracks skipped/unlearnable attributes per category
    """
    
    MIN_PREFIX_LENGTH = 3
    
    def get_sku_prefix(self, sku):
        """Get the minimum prefix for a SKU (for display purposes)."""
        if not sku or len(sku) < self.MIN_PREFIX_LENGTH:
            return sku.upper() if sku else ''
        return sku[:self.MIN_PREFIX_LENGTH].upper()
    
    def __init__(self):
        # sku_prefix -> {category_id, category_name}
        self.prefix_to_category = {}
        
        # category_id -> list of SKUs seen (for dynamic prefix calculation)
        self.category_skus = {}
        
        # category_id -> computed prefix
        self.category_prefix = {}
        
        # category_id -> list of required attribute names
        self.category_requirements = {}
        
        # category_id -> set of attributes we have rules for
        self.category_rule_coverage = {}
        
        # category_id -> {name, friendly_name}
        self.category_info = {}
        
        # category_id -> set of attributes that are skipped/unlearnable
        # (user decided to skip, counts as "covered" for completeness)
        self.category_skipped_attributes = {}
        
        # category_id -> number of SKUs verified via HTTP (for rule validation)
        # We verify first N SKUs even if rules match, to catch PS5 vs PS5 Pro issues
        self.category_verified_count = {}
    
    VERIFICATION_THRESHOLD = 5  # Verify first N SKUs per category even if rules match
    
    def _find_common_prefix(self, strings):
        """Find the longest common prefix among a list of strings."""
        if not strings:
            return ""
        if len(strings) == 1:
            # Single SKU: use first 3 chars as minimum
            return strings[0][:self.MIN_PREFIX_LENGTH].upper() if len(strings[0]) >= self.MIN_PREFIX_LENGTH else strings[0].upper()
        
        # Sort to get lexicographically first and last
        sorted_strings = sorted([s.upper() for s in strings])
        first, last = sorted_strings[0], sorted_strings[-1]
        
        # Find common prefix between first and last (covers all)
        prefix = ""
        for i in range(min(len(first), len(last))):
            if first[i] == last[i]:
                prefix += first[i]
            else:
                break
        
        # Ensure minimum length
        if len(prefix) < self.MIN_PREFIX_LENGTH:
            prefix = first[:self.MIN_PREFIX_LENGTH] if len(first) >= self.MIN_PREFIX_LENGTH else first
        
        return prefix
    
    def get_category_for_sku(self, sku):
        """
        Get category info for a SKU based on learned prefixes.
        Returns: {category_id, category_name} or None if unknown.
        """
        if not sku:
            return None
        
        sku_upper = sku.upper()
        
        # Check all known prefixes, prefer longest match
        best_match = None
        best_prefix_len = 0
        
        for prefix, cat_info in self.prefix_to_category.items():
            if sku_upper.startswith(prefix) and len(prefix) > best_prefix_len:
                best_match = cat_info
                best_prefix_len = len(prefix)
        
        return best_match
    
    def register_category(self, sku, category_id, category_name):
        """
        Register SKU to a category. Dynamically computes common prefix.
        After 2+ SKUs, prefix is refined to common characters.
        """
        if not sku:
            return
        
        # Track SKU for this category
        if category_id not in self.category_skus:
            self.category_skus[category_id] = []
        
        if sku.upper() not in [s.upper() for s in self.category_skus[category_id]]:
            self.category_skus[category_id].append(sku)
        
        # Update category info
        if category_id not in self.category_info:
            self.category_info[category_id] = {'name': category_name}
        
        # Compute/update prefix based on all SKUs for this category
        old_prefix = self.category_prefix.get(category_id)
        new_prefix = self._find_common_prefix(self.category_skus[category_id])
        
        # Remove old prefix mapping if changed
        if old_prefix and old_prefix != new_prefix and old_prefix in self.prefix_to_category:
            del self.prefix_to_category[old_prefix]
        
        # Store new prefix
        self.category_prefix[category_id] = new_prefix
        self.prefix_to_category[new_prefix] = {
            'category_id': category_id,
            'category_name': category_name
        }
    
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
    
    def mark_attribute_skipped(self, category_id, attribute_name):
        """Mark that this attribute is skipped/unlearnable for this category."""
        if category_id not in self.category_skipped_attributes:
            self.category_skipped_attributes[category_id] = set()
        self.category_skipped_attributes[category_id].add(attribute_name)
    
    def is_attribute_skipped(self, category_id, attribute_name):
        """Check if attribute is skipped for this category."""
        return attribute_name in self.category_skipped_attributes.get(category_id, set())
    
    def needs_verification(self, category_id):
        """Check if we should verify via HTTP even if rules match (first N SKUs)."""
        count = self.category_verified_count.get(category_id, 0)
        return count < self.VERIFICATION_THRESHOLD
    
    def increment_verified(self, category_id):
        """Increment verification count for a category."""
        if category_id not in self.category_verified_count:
            self.category_verified_count[category_id] = 0
        self.category_verified_count[category_id] += 1
    
    def get_missing_attributes(self, category_id):
        """
        Get list of required attributes we don't have rules for yet.
        Excludes skipped attributes (they count as handled).
        Returns empty list if all covered or requirements not set.
        """
        requirements = self.category_requirements.get(category_id)
        if not requirements:
            return []
        
        covered = self.category_rule_coverage.get(category_id, set())
        skipped = self.category_skipped_attributes.get(category_id, set())
        return [attr for attr in requirements if attr not in covered and attr not in skipped]
    
    def is_category_complete(self, category_id):
        """Check if we have rules (or skipped) for all required attributes."""
        missing = self.get_missing_attributes(category_id)
        return len(missing) == 0


class Command(BaseCommand):
    help = 'Process BOXED variants with category-aware rule-based attribute matching'

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

    def add_arguments(self, parser):
        parser.add_argument(
            '--interactive',
            action='store_true',
            help='Enable interactive prompts for manual rule definition when auto-learning fails',
        )
        parser.add_argument(
            '--output',
            type=str,
            default='process_data_results.json',
            help='Output file for results (default: process_data_results.json)',
        )
    
    def prompt_for_requirements(self, category_id, category_name, available_attributes, category_mgr):
        """
        Prompt user to select required attributes for a category.
        Shows previously used requirements as default option.
        """
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
    
    def prompt_for_manual_rule(self, title, attr_name, attr_value):
        """
        Prompt user to manually define a match rule when automatic learning fails.
        
        Returns: match_rule (string or list) or None if skipped
        """
        # Get first word of title as suggestion
        first_word = title.split()[0].lower() if title.split() else ''
        
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'  Cannot auto-learn rule for: {attr_name}'))
        self.stdout.write(f'    Title: "{title}"')
        self.stdout.write(f'    Attribute value: "{attr_value}"')
        self.stdout.write('')
        self.stdout.write('  Define match rule:')
        self.stdout.write(f'    [Enter] = Use first word: "{first_word}"')
        self.stdout.write('    [word] = Single word/phrase match')
        self.stdout.write('    [word1,word2] = Multiple words (ALL must match)')
        self.stdout.write('    [skip] = Skip this attribute')
        
        user_input = input('  > ').strip()
        
        if user_input.lower() == 'skip':
            self.stdout.write('  Skipped.')
            return None
        
        if user_input == '':
            # Use first word
            if len(first_word) >= 2:
                self.stdout.write(f'  Using: "{first_word}"')
                return first_word
            else:
                self.stdout.write(self.style.ERROR(f'  First word "{first_word}" is too short (min 2 chars). Please enter manually:'))
                user_input = input('  > ').strip()
                if user_input.lower() == 'skip' or user_input == '':
                    return None
        
        # Check if it's a comma-separated list (array)
        if ',' in user_input:
            words = [w.strip().lower() for w in user_input.split(',') if w.strip()]
            if len(words) >= 2 and all(len(w) >= 2 for w in words):
                self.stdout.write(f'  Using array: {words} (ALL must match)')
                return words
            else:
                self.stdout.write(self.style.ERROR('  Invalid array (need 2+ words, each 2+ chars). Using as single string.'))
                user_input = user_input.replace(',', ' ').strip()
        
        # Single string
        match_rule = user_input.lower()
        if len(match_rule) >= 2:
            self.stdout.write(f'  Using: "{match_rule}"')
            return match_rule
        else:
            self.stdout.write(self.style.ERROR(f'  "{match_rule}" is too short (min 2 chars). Skipped.'))
            return None

    def prompt_for_unlearnable_rule(self, sku_title, attr_name, attr_value, category_name):
        """
        Prompt ONCE when an attribute can't be auto-learned for a category.
        Returns: match_rule (str or list) if user defines one, or 'SKIP' to skip this attribute.
        """
        title_lower = sku_title.lower()
        words = re.findall(r'\b\w+\b', title_lower)
        first_word = words[0] if words else ''
        first_word_valid = len(first_word) >= 2
        
        self.stdout.write('')
        self.stdout.write(self.style.WARNING(f'  ⚠ Cannot auto-learn: {attr_name}={attr_value}'))
        self.stdout.write(f'  Category: {category_name}')
        self.stdout.write(f'  Title words: {", ".join(words[:8])}{"..." if len(words) > 8 else ""}')
        self.stdout.write('')
        self.stdout.write('  Options:')
        if first_word_valid:
            self.stdout.write(f'    [1]         Use first word: "{first_word}"')
        else:
            self.stdout.write(f'    [1]         (unavailable - "{first_word}" too short)')
        self.stdout.write('    [Enter/s]   Skip this attribute for this category')
        self.stdout.write('    [word]      Type a match rule (min 4 chars)')
        self.stdout.write('    [w1,w2]     Multiple words (ALL must appear)')
        self.stdout.write('')
        
        user_input = input('  > ').strip()
        
        # Enter or 's' = skip (safe default)
        if user_input == '' or user_input.lower() == 's' or user_input.lower() == 'skip':
            return 'SKIP'
        
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
        else:
            self.stdout.write(self.style.ERROR(f'  Too short (min 2 chars). Skipping attribute.'))
            return 'SKIP'

    def handle(self, *args, **options):
        """Main command handler"""
        self.interactive = options.get('interactive', False)
        output_file = options.get('output', 'process_data_results.json')
        
        engine = AttributeMatchRuleEngine()
        category_mgr = CategoryManager()
        
        # Load filter files for pre-generating rules
        self.stdout.write('Loading filter files...')
        engine.load_filter_files(stdout=self.stdout)
        self.stdout.write('')
        
        # Get BOXED variants
        boxed_condition = ConditionGrade.objects.filter(code='BOXED').first()
        if not boxed_condition:
            self.stdout.write(self.style.WARNING('No BOXED condition grade found'))
            return
        
        variants = Variant.objects.filter(condition_grade=boxed_condition)
        total = variants.count()
        
        if total == 0:
            self.stdout.write(self.style.WARNING('No BOXED variants found'))
            return
        
        mode = "INTERACTIVE" if self.interactive else "AUTOMATIC"
        self.stdout.write(f'Processing {total} BOXED variants in {mode} mode...\n')
        
        http_requests = 0
        rule_matches = 0
        self.results = []
        
        for idx, variant in enumerate(variants, 1):
            sku = variant.cex_sku
            sku_title = variant.title or sku
            
            # Initialize result entry for this SKU
            sku_result = {
                'sku': sku,
                'title': sku_title,
                'category': None,
                'source': None,  # 'rule_match' or 'http'
                'attributes': {},
                'unlearnable': []
            }
            
            self.stdout.write(f'\n[{idx}/{total}] SKU: {sku}')
            self.stdout.write(f'  Title: {sku_title}')
            
            # Step 1: Determine category from SKU prefix
            category_info = category_mgr.get_category_for_sku(sku)
            
            if category_info:
                category_id = category_info['category_id']
                category_name = category_info['category_name']
                sku_result['category'] = category_name
                self.stdout.write(f'  Category (from prefix): {category_name}')
                
                # Check if category requirements are complete
                if category_mgr.is_category_complete(category_id):
                    # All required attributes have rules - try to match
                    required_attrs = category_mgr.get_requirements(category_id)
                    matched_attrs = engine.apply_rules_to_sku(sku_title, required_attrs)
                    
                    # Check if ALL required attributes matched
                    if required_attrs and all(attr in matched_attrs for attr in required_attrs):
                        # Check if we still need to verify (first N SKUs)
                        if category_mgr.needs_verification(category_id):
                            self.stdout.write(f'  Rules matched, but verifying via HTTP (verification #{category_mgr.category_verified_count.get(category_id, 0) + 1}/{category_mgr.VERIFICATION_THRESHOLD})...')
                            # Don't continue - fall through to HTTP to verify
                        else:
                            rule_matches += 1
                            sku_result['source'] = 'rule_match'
                            sku_result['attributes'] = matched_attrs
                            self.results.append(sku_result)
                            self.stdout.write(self.style.SUCCESS(f'  RULE MATCH (all required): {json.dumps(matched_attrs)}'))
                            continue
                    else:
                        # Some required attributes didn't match - need HTTP
                        missing = [a for a in required_attrs if a not in matched_attrs]
                        self.stdout.write(f'  Missing matches for: {missing}')
                else:
                    missing = category_mgr.get_missing_attributes(category_id)
                    self.stdout.write(f'  Category incomplete. Missing rules for: {missing}')
            else:
                self.stdout.write(f'  Category unknown (new prefix: {category_mgr.get_sku_prefix(sku)})')
                category_id = None
            
            # Need HTTP request
            self.stdout.write(f'  Fetching from API...')
            http_requests += 1
            sku_result['source'] = 'http'
            
            result = self.fetch_sku_details(sku)
            if not result:
                self.results.append(sku_result)
                continue
            
            box_details = result.get('response', {}).get('data', {}).get('boxDetails', [])
            if not box_details:
                self.stdout.write(self.style.WARNING('  No box details in response'))
                self.results.append(sku_result)
                continue
            
            box = box_details[0]
            api_category_id = box.get('categoryId')
            api_category_name = box.get('categoryName', 'Unknown')
            attribute_info = box.get('attributeInfo', []) or []
            
            sku_result['category'] = api_category_name
            
            # Register category mapping
            category_mgr.register_category(sku, api_category_id, api_category_name)
            self.stdout.write(f'  Category (from API): {api_category_name} (ID: {api_category_id})')
            
            # Register friendly name -> attribute name mappings (needed for pre-generation)
            for attr in attribute_info:
                attr_name = attr.get('attributeName', '')
                friendly_name = attr.get('attributeFriendlyName', '')
                if attr_name and friendly_name:
                    engine.register_friendly_name_mapping(friendly_name, attr_name)
            
            # If this is a new category (no requirements set), prompt user
            if category_mgr.get_requirements(api_category_id) is None:
                if attribute_info:
                    available_attrs = [attr.get('attributeName', '') for attr in attribute_info if attr.get('attributeName')]
                    required = self.prompt_for_requirements(api_category_id, api_category_name, available_attrs, category_mgr)
                    category_mgr.set_requirements(api_category_id, required)
                    
                    # Pre-generate rules from filter file for this category
                    engine.pregenerate_rules_for_category(api_category_name, stdout=self.stdout)
                    
                    # Mark coverage for required attributes that now have rules
                    for attr_name in required:
                        if attr_name in engine.rules and len(engine.rules[attr_name]) > 0:
                            category_mgr.mark_attribute_covered(api_category_id, attr_name)
                else:
                    self.stdout.write('  No attributes available for this category')
                    category_mgr.set_requirements(api_category_id, [])
            
            # Get required attributes for this category
            required_attrs = category_mgr.get_requirements(api_category_id) or []
            
            if not attribute_info:
                self.stdout.write('  No attribute info in response')
                self.results.append(sku_result)
                continue
            
            # Check if this is a verification request
            is_verification = category_mgr.needs_verification(api_category_id)
            if is_verification:
                category_mgr.increment_verified(api_category_id)
            
            # Get rule predictions for comparison during verification
            rule_predictions = {}
            if is_verification:
                rule_predictions = engine.apply_rules_to_sku(sku_title, required_attrs)
            
            # Learn rules for REQUIRED attributes only
            learned = []
            for attr in attribute_info:
                attr_name = attr.get('attributeName', '')
                attr_values = attr.get('attributeValue', [])
                
                if not attr_name or not attr_values:
                    continue
                
                # Only learn rules for required attributes
                if attr_name not in required_attrs:
                    continue
                
                attr_value = attr_values[0] if isinstance(attr_values, list) else str(attr_values)
                
                # Store attribute value from HTTP (ground truth)
                sku_result['attributes'][attr_name] = attr_value
                
                # During verification: check if rule prediction differs from API value
                if is_verification and attr_name in rule_predictions:
                    predicted = rule_predictions[attr_name]
                    if predicted != attr_value:
                        self.stdout.write(self.style.WARNING(
                            f'  MISMATCH: {attr_name} rule predicted "{predicted}" but API says "{attr_value}"'
                        ))
                        # Try to learn a more specific rule for the correct value
                        rule = engine.learn_rule_from_sku(sku_title, attr_name, attr_value)
                        if rule:
                            stored = engine.store_rule(rule, source_sku=sku, source_title=sku_title)
                            if stored:
                                match_rule = rule['match_rule']
                                if isinstance(match_rule, list):
                                    self.stdout.write(self.style.SUCCESS(f'  CORRECTED: {attr_name}={attr_value} via {match_rule}'))
                                else:
                                    self.stdout.write(self.style.SUCCESS(f'  CORRECTED: {attr_name}={attr_value} via "{match_rule}"'))
                            # Mark coverage for corrected rule
                            category_mgr.mark_attribute_covered(api_category_id, attr_name)
                        continue
                    else:
                        # Rule prediction was correct - mark coverage
                        category_mgr.mark_attribute_covered(api_category_id, attr_name)
                        self.stdout.write(f'  VERIFIED: {attr_name}={attr_value} ✓')
                        continue
                
                # Skip if we already have coverage for this attribute in this category
                if attr_name in category_mgr.category_rule_coverage.get(api_category_id, set()):
                    continue
                
                # Skip if this attribute was already marked as skipped for this category
                if category_mgr.is_attribute_skipped(api_category_id, attr_name):
                    sku_result['unlearnable'].append({
                        'attribute': attr_name,
                        'value': attr_value,
                        'reason': 'Attribute skipped for this category'
                    })
                    continue
                
                # Try automatic rule learning
                rule = engine.learn_rule_from_sku(sku_title, attr_name, attr_value)
                
                # If automatic learning failed
                if not rule:
                    if self.interactive:
                        # Interactive mode: prompt ONCE for unlearnable attributes
                        category_name = category_mgr.category_info.get(api_category_id, {}).get('name', 'Unknown')
                        user_response = self.prompt_for_unlearnable_rule(
                            sku_title, attr_name, attr_value, category_name
                        )
                        
                        if user_response == 'SKIP':
                            # Mark as skipped for this category - won't ask again
                            category_mgr.mark_attribute_skipped(api_category_id, attr_name)
                            sku_result['unlearnable'].append({
                                'attribute': attr_name,
                                'value': attr_value,
                                'reason': 'User skipped for this category'
                            })
                            self.stdout.write(f'  SKIPPED: {attr_name} for category "{category_name}" (won\'t ask again)')
                        elif user_response:
                            # User provided a match rule
                            rule = {
                                'attribute': attr_name,
                                'value': attr_value,
                                'match_rule': user_response
                            }
                    else:
                        # Auto mode: just log and continue (no prompts)
                        sku_result['unlearnable'].append({
                            'attribute': attr_name,
                            'value': attr_value,
                            'reason': 'No match pattern found in title'
                        })
                        self.stdout.write(f'  SKIP: {attr_name}={attr_value} (no auto-match possible)')
                
                if rule:
                    stored = engine.store_rule(rule, source_sku=sku, source_title=sku_title)
                    
                    # ALWAYS mark category as covered if we have a valid rule
                    # (even if it's a duplicate from another category)
                    category_mgr.mark_attribute_covered(api_category_id, attr_name)
                    
                    if stored:
                        learned.append(rule)
                        match_rule = rule['match_rule']
                        if isinstance(match_rule, list):
                            self.stdout.write(f'  LEARNED: {attr_name}={attr_value} via {match_rule} (ALL must match)')
                        else:
                            self.stdout.write(f'  LEARNED: {attr_name}={attr_value} via "{match_rule}"')
                    else:
                        # Rule already exists - still mark as covered for this category
                        self.stdout.write(f'  REUSED: {attr_name}={attr_value} (rule already exists)')
            
            self.results.append(sku_result)
            
            # Show category progress
            missing = category_mgr.get_missing_attributes(api_category_id)
            skipped = category_mgr.category_skipped_attributes.get(api_category_id, set())
            if missing:
                self.stdout.write(f'  Category progress: still need rules for {missing}')
            else:
                if skipped:
                    self.stdout.write(self.style.SUCCESS(f'  Category COMPLETE (skipped: {list(skipped)})'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'  Category COMPLETE: all required attributes have rules!'))
        
        # Summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write('SUMMARY:')
        self.stdout.write(f'  Total variants processed: {total}')
        self.stdout.write(f'  HTTP requests made: {http_requests}')
        self.stdout.write(f'  Rule matches (no HTTP): {rule_matches}')
        
        # Count rules by source
        total_rules = sum(len(r) for r in engine.rules.values())
        preloaded_rules = sum(1 for rules_list in engine.rules.values() for r in rules_list if r.get('source_sku') == 'preloaded')
        learned_rules = total_rules - preloaded_rules
        self.stdout.write(f'  Total rules: {total_rules}')
        self.stdout.write(f'    - Pre-generated from filters: {preloaded_rules}')
        self.stdout.write(f'    - Learned from SKUs: {learned_rules}')
        
        # Count unlearnable
        unlearnable_count = sum(len(r['unlearnable']) for r in self.results)
        self.stdout.write(f'  Unlearnable attributes: {unlearnable_count}')
        
        # Category summary
        self.stdout.write(f'\nCATEGORY SUMMARY:')
        for cat_id, info in category_mgr.category_info.items():
            requirements = category_mgr.get_requirements(cat_id) or []
            covered = category_mgr.category_rule_coverage.get(cat_id, set())
            skipped = category_mgr.category_skipped_attributes.get(cat_id, set())
            missing = category_mgr.get_missing_attributes(cat_id)
            status = "COMPLETE" if not missing else f"INCOMPLETE (missing: {missing})"
            
            self.stdout.write(f'\n  {info["name"]} (ID: {cat_id}):')
            self.stdout.write(f'    Required: {requirements}')
            self.stdout.write(f'    Covered (has rules): {list(covered)}')
            if skipped:
                self.stdout.write(f'    Skipped (unlearnable): {list(skipped)}')
            self.stdout.write(f'    Status: {status}')
        
        # SKU prefix mappings (dynamically determined)
        self.stdout.write(f'\nSKU PREFIX MAPPINGS:')
        for cat_id, prefix in category_mgr.category_prefix.items():
            cat_name = category_mgr.category_info.get(cat_id, {}).get('name', 'Unknown')
            sku_count = len(category_mgr.category_skus.get(cat_id, []))
            self.stdout.write(f'  {prefix}* → {cat_name} (ID: {cat_id}, based on {sku_count} SKUs)')
        
        # All learned rules
        if engine.rules:
            self.stdout.write(f'\nALL LEARNED RULES:')
            for attr_name, rules_list in engine.rules.items():
                self.stdout.write(f'\n  {attr_name}:')
                for rule in rules_list:
                    match_rule = rule['match_rule']
                    if isinstance(match_rule, list):
                        match_display = f'{match_rule} (ALL must match)'
                    else:
                        match_display = f'"{match_rule}"'
                    
                    self.stdout.write(f'    - value: "{rule["value"]}"')
                    self.stdout.write(f'      match_rule: {match_display}')
                    self.stdout.write(f'      learned from: {rule.get("source_sku", "unknown")}')
        
        # Save results to JSON file
        output_data = {
            'summary': {
                'total_processed': total,
                'http_requests': http_requests,
                'rule_matches': rule_matches,
                'rules_learned': sum(len(r) for r in engine.rules.values()),
                'unlearnable_count': unlearnable_count
            },
            'categories': {
                str(cat_id): {
                    'name': info['name'],
                    'requirements': category_mgr.get_requirements(cat_id) or [],
                    'covered': list(category_mgr.category_rule_coverage.get(cat_id, set())),
                    'complete': category_mgr.is_category_complete(cat_id)
                }
                for cat_id, info in category_mgr.category_info.items()
            },
            'sku_prefixes': {
                prefix: cat_info
                for prefix, cat_info in category_mgr.prefix_to_category.items()
            },
            'rules': engine.rules,
            'results': self.results
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        self.stdout.write(self.style.SUCCESS(f'\nResults saved to: {output_file}'))
