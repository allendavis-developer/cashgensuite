// ============================================
// DOM ELEMENT REFERENCES
// ============================================

const scrapeEbayBtn = document.getElementById('scrapeEbayBtn');
const ebayModal = document.getElementById('ebayModal');
const ebaySearchInput = document.getElementById('ebaySearchInput');
const ebayWizardBtn = document.getElementById('ebayWizardBtn');
const ebayFiltersContainer = document.getElementById('ebayFiltersContainer');
const ebayResultsContainer = document.getElementById('ebayResultsContainer');
const ebayApplyBtn = document.getElementById('ebayApplyBtn');
const ebayCancelBtn = document.getElementById('ebayCancelBtn');
const ebaySelectedCount = document.getElementById('ebaySelectedCount');
const filterSoldCheckbox = document.getElementById('filterSold');
const filterUKCheckbox = document.getElementById('filterUK');
const filterUsedCheckbox = document.getElementById('filterUsed');
const rrpInput = document.getElementById('ebaySuggestedRrp');
const marginInput = document.getElementById('ebayMinMargin');
const offerInput = document.getElementById('ebayOfferValue');

// ============================================
// STATE VARIABLES
// ============================================

let selectedFilters = {};
let previousSelectedFilters = {};
let isEbayScraping = false;
let ebayWizardStep = 1; // 1 = fetch filters, 2 = ready to search

// ============================================
// EVENT LISTENERS
// ============================================

// Open modal
scrapeEbayBtn.addEventListener('click', () => {
  ebayModal.classList.add('active');
  ebaySearchInput.focus();
});

// Cancel button
ebayCancelBtn.addEventListener('click', () => {
  closeModal();
});

// Enter key to search
ebaySearchInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') {
    ebayWizardBtn.click();
  }
});

// Search input changes - reset wizard step
ebaySearchInput.addEventListener('input', () => {
  if (ebaySearchInput.value.trim() !== window.wizardState.ebay?.searchTerm) {
    ebayWizardStep = 1;
    ebayWizardBtn.textContent = 'Next';
    selectedFilters = {};
    previousSelectedFilters = {};
    ebayFiltersContainer.innerHTML = '';
    ebayResultsContainer.innerHTML = '';
    updateSelectedCount();
  }
});

// Wizard button - two-step flow
ebayWizardBtn.addEventListener('click', async () => {
  const searchTerm = ebaySearchInput.value.trim();
  if (!searchTerm) {
    alert('Please enter a search term');
    return;
  }

  if (ebayWizardStep === 1) {
    // Step 1: fetch filters
    ebayFiltersContainer.style.display = 'block';
    ebayResultsContainer.style.display = 'none';
    ebayFiltersContainer.innerHTML = '<div style="text-align:center; padding:20px; color:#666;">Loading filters...</div>';

    try {
      const response = await fetch(`/api/ebay/filters/?q=${encodeURIComponent(searchTerm)}`, {
        method: "GET",
        headers: { "Accept": "application/json" }
      });

      if (!response.ok) throw new Error("Failed to fetch filters");

      const data = await response.json();
      renderFilters(data.filters);

      ebayWizardStep = 2;
      ebayWizardBtn.textContent = 'Search';

    } catch (err) {
      console.error('Error fetching filters:', err);
      ebayFiltersContainer.innerHTML = '<div style="text-align:center; padding:20px; color:#c00;">Error loading filters. Please try again.</div>';
    }

  } else if (ebayWizardStep === 2) {
    // Step 2: scrape eBay with filters
    runEbayScrape(); // call scraping logic directly
  }
});

async function runEbayScrape() {
    if (isEbayScraping) return;
    resetEbayAnalysis(); 

    const searchTerm = ebaySearchInput.value.trim();
    if (!searchTerm) {
        alert('Please enter a search term');
        return;
    }

    setEbayScrapingState(true);

    const ebayFilterSold = filterSoldCheckbox.checked;
    const ebayFilterUKOnly = filterUKCheckbox.checked;
    const ebayFilterUsed = filterUsedCheckbox.checked;

    // Get selected category from TomSelect
    const categoryInputValue = ebayCategoryTomSelect?.getValue() || '';
    const categoryText = ebayCategoryTomSelect?.options[categoryInputValue]?.text || '';
    
    // Build the options object for buildEbayUrl
    const options = {
        category: categoryText.toLowerCase(), // lowercase for mapping
        model: window.wizardState.ebay?.model || '', // if you store model in wizard state
        attributes: window.wizardState.ebay?.attributes || {}, // e.g., { storage: "256GB" }
        ebayFilterSold,
        ebayFilterUsed,
        ebayFilterUKOnly
    };

    // Build eBay URL
    const ebayUrl = buildEbayUrl(searchTerm, selectedFilters, options);

    ebayResultsContainer.style.display = 'block';
    ebayResultsContainer.innerHTML = '<div style="text-align: center; padding: 40px; color: #666;">Scraping eBay listings...</div>';

    try {
        previousSelectedFilters = JSON.parse(JSON.stringify(selectedFilters));

        const response = await sendExtensionMessage({
            action: "scrape",
            data: {
                directUrl: ebayUrl,
                competitors: ["eBay"],
                ebayFilterSold,
                ebayFilterUsed,
                ebayFilterUKOnly
            }
        });

      // After you get the response
      if (response.success) {
          // Keep only the first 20 listings
          const listings = response.results.slice(0, 20);

          const rawPrices = listings
              .map(item => Number(item.price))
              .filter(p => !isNaN(p) && p > 0);

          const cleanedPrices = removeOutliers(rawPrices);
          window._ebayPriceCache = { rawPrices, cleanedPrices };

          const cleanedSet = new Set(
              cleanedPrices.map(p => Number(p.toFixed(2)))
          );

          listings.forEach(item => {
              const price = Number(Number(item.price).toFixed(2));
              item.isAnomalous = !cleanedSet.has(price);
          });

          window.currentEbayResults = listings;

          renderResults(listings);
          updateVisibleEbayCount();

          const stats = calculateStats(cleanedPrices);
          document.getElementById('ebay-min').textContent = stats.min;
          document.getElementById('ebay-avg').textContent = stats.avg;
          document.getElementById('ebay-median').textContent = stats.median;
          document.getElementById('ebay-mode').textContent = stats.mode;

          // Suggested RRP
          const avgNum = Number(stats.avg);
          if (!isNaN(avgNum)) {
              rrpInput.value = Math.round(avgNum);
              offerInput.value = (Math.round(avgNum) * 0.4).toFixed(0);
          }

          if (marginInput && !marginInput.value) {
              marginInput.value = 50;
              recalculateOfferValue();
          }

          refreshFiltersFromUrl(ebayUrl);
      } else {
            alert("Scraping failed: " + (response.error || "Unknown error"));
        }
    } catch (error) {
        console.error("Scraping error:", error);
        alert("Error running scraper: " + error.message);
    } finally {
        setEbayScrapingState(false);
        saveEbayWizardState();
    }
}

// Top filter checkboxes - save state on change
[filterSoldCheckbox, filterUKCheckbox, filterUsedCheckbox].forEach(cb => {
  cb.addEventListener('change', saveEbayWizardState);
});

// Pricing inputs - recalculate and save
rrpInput.addEventListener('input', () => {
  recalculateOfferValue();
  saveEbayWizardState();
});

marginInput.addEventListener('input', () => {
  recalculateOfferValue();
  saveEbayWizardState();
});

// Back button
document.querySelector('.rw-back-ebay')?.addEventListener('click', () => {
  saveEbayWizardState();
  window.ResearchWizard.showOverview();
});

document.getElementById('ebayShowAnomalies')?.addEventListener('change', e => {
  const cache = window._ebayPriceCache;
  if (!cache) return;

  const prices = document.getElementById('ebayShowAnomalies').checked
    ? cache.rawPrices
    : cache.cleanedPrices;

  const stats = calculateStats(prices);

  document.getElementById('ebay-min').textContent = stats.min;
  document.getElementById('ebay-avg').textContent = stats.avg;
  document.getElementById('ebay-median').textContent = stats.median;
  document.getElementById('ebay-mode').textContent = stats.mode;

  // keep your existing RRP logic intact
  const medianNum = Number(stats.median);
  if (!isNaN(medianNum)) {
    let rounded = Math.round(medianNum);
    let suggestedRrp = (rounded % 2 === 0) ? rounded - 2 : rounded - 1;
    if (suggestedRrp < 0) suggestedRrp = 0;
    rrpInput.value = suggestedRrp.toFixed(0);
    recalculateOfferValue();
  }

  const show = e.target.checked;

  document
    .querySelectorAll('.ebay-listing-card[data-anomalous="true"]')
    .forEach(card => {
      card.style.display = show ? 'flex' : 'none';
    });

  saveEbayWizardState();
  updateVisibleEbayCount();

});


function updateVisibleEbayCount() {
  const cards = Array.from(
    document.querySelectorAll('.ebay-listing-card')
  );

  const visibleCount = cards.filter(card =>
    card.style.display !== 'none'
  ).length;

  const counter = document.getElementById('ebay-visible-count');
  if (counter) {
    counter.textContent = visibleCount;
  }
}


// ============================================
// FILTER RENDERING & INTERACTION
// ============================================

function renderFilters(filters) {
  selectedFilters = {};
  updateSelectedCount();
  
  ebayFiltersContainer.innerHTML = filters.map(filter => {
    if (filter.type === 'checkbox') {
      const sortedOptions = [...filter.options].sort((a, b) => (b.count ?? 0) - (a.count ?? 0));
      return `
        <div class="ebay-filter-section">
          <h4 class="ebay-filter-title">
            <span class="ebay-filter-arrow">▶</span>
            ${filter.name}
          </h4>
          <div class="ebay-filter-options">
            ${sortedOptions.map(option => `
              <label class="ebay-filter-option">
                <input type="checkbox" 
                       data-filter="${filter.name}" 
                       data-value="${option.label}"
                       class="ebay-filter-checkbox">
                <span>${option.label}</span>
                ${option.count ? `<span class="ebay-filter-count">(${option.count.toLocaleString()})</span>` : ''}
              </label>
            `).join('')}
          </div>
        </div>
      `;
    } else if (filter.type === 'range') {
      return `
        <div class="ebay-filter-section">
          <h4 class="ebay-filter-title">
            <span class="ebay-filter-arrow">▶</span>
            ${filter.name}
          </h4>
          <div class="ebay-filter-range">
            <input type="number" 
                   placeholder="Min" 
                   data-filter="${filter.name}" 
                   data-range="min"
                   class="ebay-range-input">
            <span style="margin: 0 8px;">to</span>
            <input type="number" 
                   placeholder="Max" 
                   data-filter="${filter.name}" 
                   data-range="max"
                   class="ebay-range-input">
          </div>
        </div>
      `;
    }
  }).join('');

  attachFilterListeners();

  const savedFilters = window.wizardState?.ebay?.filters;
  if (savedFilters) {
    restoreFilterSelections(savedFilters);
  }
}

function attachFilterListeners() {
  ebayFiltersContainer.querySelectorAll('.ebay-filter-checkbox')
    .forEach(cb => cb.addEventListener('change', handleFilterChange));

  ebayFiltersContainer.querySelectorAll('.ebay-range-input')
    .forEach(input => input.addEventListener('input', handleFilterChange));

  ebayFiltersContainer.querySelectorAll('.ebay-filter-title')
    .forEach(title => {
      title.addEventListener('click', () => {
        title.closest('.ebay-filter-section').classList.toggle('expanded');
      });
    });
}

function handleFilterChange(e) {
  const filterName = e.target.dataset.filter;
  
  if (e.target.type === 'checkbox') {
    if (!selectedFilters[filterName]) {
      selectedFilters[filterName] = [];
    }
    
    if (e.target.checked) {
      selectedFilters[filterName].push(e.target.dataset.value);
    } else {
      selectedFilters[filterName] = selectedFilters[filterName].filter(v => v !== e.target.dataset.value);
      if (selectedFilters[filterName].length === 0) {
        delete selectedFilters[filterName];
      }
    }
  } else if (e.target.classList.contains('ebay-range-input')) {
    const rangeType = e.target.dataset.range;
    if (!selectedFilters[filterName]) {
      selectedFilters[filterName] = {};
    }
    selectedFilters[filterName][rangeType] = e.target.value;
  }
  
  updateSelectedCount();

  const section = e.target.closest('.ebay-filter-section');
  if (section && !section.classList.contains('expanded')) {
    section.classList.add('expanded');
  }

  saveEbayWizardState();
}

function updateSelectedCount() {
  let count = 0;
  Object.values(selectedFilters).forEach(value => {
    if (Array.isArray(value)) {
      count += value.length;
    } else if (typeof value === 'object') {
      if (value.min || value.max) count++;
    }
  });
  
  ebaySelectedCount.textContent = count;
}

function restoreFilterSelections(restoreFilters) {
  Object.entries(restoreFilters).forEach(([filterName, value]) => {
    // Checkbox filters
    if (Array.isArray(value)) {
      value.forEach(v => {
        const checkbox = ebayFiltersContainer.querySelector(
          `.ebay-filter-checkbox[data-filter="${filterName}"][data-value="${CSS.escape(v)}"]`
        );

        if (checkbox) {
          checkbox.checked = true;
          checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }
      });
    }

    // Range filters
    if (typeof value === 'object' && !Array.isArray(value)) {
      ['min', 'max'].forEach(rangeType => {
        if (value[rangeType]) {
          const input = ebayFiltersContainer.querySelector(
            `.ebay-range-input[data-filter="${filterName}"][data-range="${rangeType}"]`
          );

          if (input) {
            input.value = value[rangeType];
            input.dispatchEvent(new Event('input', { bubbles: true }));
          }
        }
      });
    }
  });
}

async function refreshFiltersFromUrl(ebayUrl) {
  ebayFiltersContainer.innerHTML =
    '<div style="text-align:center; padding:20px; color:#666;">Updating filters...</div>';
  ebayFiltersContainer.style.display = 'block';

  try {
    const response = await fetch(
      `/api/ebay/filters/?url=${encodeURIComponent(ebayUrl)}`,
      {
        method: "GET",
        headers: { "Accept": "application/json" }
      }
    );

    if (!response.ok) {
      throw new Error("Failed to refresh filters");
    }

    const data = await response.json();
    renderFilters(data.filters, previousSelectedFilters);

  } catch (err) {
    console.error("Filter refresh failed:", err);
  }
}

// ============================================
// URL BUILDING
// ============================================

function buildEbayUrl(searchTerm, filters, options = {}) {
  const { category, model, attributes, ebayFilterSold, ebayFilterUsed, ebayFilterUKOnly } = options;

  const baseUrl = "https://www.ebay.co.uk/sch/i.html";

  // Map internal category to eBay category IDs
  const categoryMap = {
    "smartphones and mobile": "9355",
    "games (discs & cartridges)": "139973",
    "tablets": "58058",
    "laptops": "175672",
    "gaming consoles": "139971",
    "cameras": "31388",
    "headphones": "15052",
    "smartwatches": "178893"
  };
  
  const normalizedCategory = (category || "").toLowerCase();
  const categoryId = categoryMap[normalizedCategory] || null;

  const encoded = encodeURIComponent(searchTerm);

  // Build base URL depending on category
  let url;
  if (!categoryId) {
    url = `https://www.ebay.co.uk/sch/i.html?_nkw=${encoded}&_sacat=0&_sop=12&_oac=1&_ipg=240`;
  } else {
    url = `https://www.ebay.co.uk/sch/${categoryId}/i.html?_nkw=${encoded}&_sop=12&_oac=1&_ipg=240`;
  }

  // Handle model (smartphones only)
  if (model && normalizedCategory === "smartphones and mobile") {
    const normalizedModel = model.replace(/iphone/i, "iPhone");
    const doubleEncoded = encodeURIComponent(normalizedModel).replace(/%/g, "%25");
    url += `&Model=${doubleEncoded}`;
  }

  // Handle storage attribute
  if (attributes?.storage) {
    let storage = attributes.storage.toUpperCase().trim();
    storage = storage.replace(/^(\d+)(GB)$/, "$1 $2");
    const doubleEncodedStorage = encodeURIComponent(storage).replace(/%/g, "%25");
    url += `&Storage%2520Capacity=${doubleEncodedStorage}`;
  }

  // Optional eBay filters
  if (ebayFilterSold) url += "&LH_Sold=1&LH_Complete=1";
  if (ebayFilterUsed) url += "&LH_ItemCondition=3000";
  if (ebayFilterUKOnly) url += "&LH_PrefLoc=1";

  // --- Filter block (keep untouched) ---
  Object.entries(filters).forEach(([filterName, value]) => {
    if (Array.isArray(value)) {
      const doubleEncodedKey = encodeURIComponent(encodeURIComponent(filterName));
      const doubleEncodedValue = value
        .map(v => encodeURIComponent(encodeURIComponent(v)))
        .join("|");
      url += `&${doubleEncodedKey}=${doubleEncodedValue}`;
    } else if (typeof value === 'object') {
      const doubleEncodedKey = encodeURIComponent(encodeURIComponent(filterName));
      if (value.min) url += `&${doubleEncodedKey}_min=${encodeURIComponent(encodeURIComponent(value.min))}`;
      if (value.max) url += `&${doubleEncodedKey}_max=${encodeURIComponent(encodeURIComponent(value.max))}`;
    } else {
      const doubleEncodedKey = encodeURIComponent(encodeURIComponent(filterName));
      url += `&${doubleEncodedKey}=${encodeURIComponent(encodeURIComponent(value))}`;
    }
  });

  return url;
}


// ============================================
// RESULTS RENDERING
// ============================================
// Disable the Complete button by default
ebayApplyBtn.disabled = true;
ebayApplyBtn.classList.add('disabled');


function renderResults(results) {
  if (!results || results.length === 0) {
    ebayResultsContainer.innerHTML = `
      <div style="text-align:center; padding:40px; color:#666;">
        No eBay listings found.
      </div>
    `;
    return;
  }

  ebayResultsContainer.innerHTML = `
    <div class="ebay-results-header">
      <h3>eBay Listings (<span id="ebay-visible-count">0</span>  results)</h3>
    </div>

    <div class="ebay-listings">
      ${results.map(item => `
          <div
            class="ebay-listing-card"
            data-anomalous="${item.isAnomalous}"
            style="display:flex; gap:15px; padding:12px;"
          >
          
          ${item.image ? `
            <img
              src="${item.image}"
              alt="${item.title || "eBay listing"}"
              class="ebay-listing-image"
              loading="lazy"
            />
          ` : ""}

          <div class="ebay-listing-content">
            <a
              href="${item.url}"
              target="_blank"
              rel="noopener"
              class="ebay-listing-title"
            >
              ${item.title || "Untitled listing"}
            </a>

            <div class="ebay-listing-details">
              <span class="ebay-listing-price">
                £${Number(item.price).toFixed(2)}
              </span>
            </div>

            ${item.store ? `
              <div class="ebay-listing-seller">
                Seller: ${item.store}
              </div>
            ` : ""}
          </div>

        </div>
      `).join("")}
    </div>
  `;

    // Enable the Complete button now that there are results
  ebayApplyBtn.disabled = false;
  ebayApplyBtn.classList.remove('disabled');

  updateVisibleEbayCount();

}

// ============================================
// STATS & CALCULATIONS
// ============================================

function removeOutliers(prices) {
  if (prices.length < 4) return prices;

  // --- Step 0: keep only valid positive prices
  const valid = prices.filter(p => p > 0);
  if (valid.length < 4) return prices;

  // --- Step 1: semantic floor (meaning before statistics)
  const sortedLinear = [...valid].sort((a, b) => a - b);

  const median = (() => {
    const mid = Math.floor(sortedLinear.length / 2);
    return sortedLinear.length % 2 === 0
      ? (sortedLinear[mid - 1] + sortedLinear[mid]) / 2
      : sortedLinear[mid];
  })();

  // Anything below X% of median is probably accessories / junk
  const FLOOR_RATIO = 0.25;
  const semanticFiltered = valid.filter(p => p >= median * FLOOR_RATIO);

  // If semantic filtering nukes too much data, fall back
  if (semanticFiltered.length < 4) {
    return semanticFiltered;
  }

  // --- Step 2: log-space IQR
  const pairs = semanticFiltered.map(p => ({
    price: p,
    log: Math.log(p)
  }));

  pairs.sort((a, b) => a.log - b.log);

  const percentile = (arr, p) => {
    const index = (arr.length - 1) * p;
    const lower = Math.floor(index);
    const upper = Math.ceil(index);
    if (lower === upper) return arr[lower].log;
    return (
      arr[lower].log +
      (arr[upper].log - arr[lower].log) * (index - lower)
    );
  };

  const q1 = percentile(pairs, 0.25);
  const q3 = percentile(pairs, 0.75);
  const iqr = q3 - q1;

  // --- Step 3: asymmetric tolerance (cheap strict, expensive forgiving)
  const lowerBound = q1 - 1.5 * iqr;
  const upperBound = q3 + 3.0 * iqr;

  return pairs
    .filter(p => p.log >= lowerBound && p.log <= upperBound)
    .map(p => p.price);
}

// ============================================
// CATEGORY SELECTOR (eBay)
// ============================================

const ebayCategorySelectEl = document.getElementById('ebayCategorySelect');
let ebayCategoryTomSelect;

// Local cache
const ebayCategoryCache = {
  categories: []
};

// Init on load
document.addEventListener('DOMContentLoaded', async () => {
  initEbayCategorySelect();
  await preloadEbayCategories();
  populateEbayCategories();
});

// --------------------------------------------
// TomSelect init
// --------------------------------------------
function initEbayCategorySelect() {
  ebayCategoryTomSelect = new TomSelect('#ebayCategorySelect', {
    placeholder: 'Select category…',
    create: false,
    allowEmptyOption: true
  });

  ebayCategoryTomSelect.on('change', value => {
    if (!value) return;

    const option = ebayCategoryTomSelect.options[value];

    // Persist to wizard state
    window.wizardState.ebay = window.wizardState.ebay || {};
    window.wizardState.ebay.category = {
      id: value,
      name: option?.text || null
    };

    console.log('eBay category selected:', window.wizardState.ebay.category);
  });
}

// --------------------------------------------
// Fetch + cache
// --------------------------------------------
async function preloadEbayCategories() {
  try {
    const res = await fetch('/api/categories/');
    const data = await res.json();
    ebayCategoryCache.categories = data.categories || [];
  } catch (err) {
    console.error('Failed to load eBay categories:', err);
  }
}

// --------------------------------------------
// Populate dropdown
// --------------------------------------------
function populateEbayCategories() {
  ebayCategoryTomSelect.clear();
  ebayCategoryTomSelect.clearOptions();

  ebayCategoryCache.categories.forEach(cat => {
    ebayCategoryTomSelect.addOption({
      value: cat.id,
      text: cat.name
    });
  });

  ebayCategoryTomSelect.refreshOptions(false);
}


function calculateStats(prices) {
  if (!prices.length) {
    return {
      min: '-',
      avg: '-',
      median: '-',
      mode: '-'
    };
  }

  const sorted = [...prices].sort((a, b) => a - b);

  // Min
  const min = sorted[0];

  // Average
  const avg = sorted.reduce((sum, p) => sum + p, 0) / sorted.length;

  // Median
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0
      ? (sorted[mid - 1] + sorted[mid]) / 2
      : sorted[mid];

  // Mode
  const frequency = {};
  let mode = sorted[0];
  let maxCount = 1;

  for (const price of sorted) {
    frequency[price] = (frequency[price] || 0) + 1;

    if (frequency[price] > maxCount) {
      maxCount = frequency[price];
      mode = price;
    }
  }

  return {
    min: min.toFixed(2),
    avg: avg.toFixed(2),
    median: median.toFixed(2),
    mode: mode.toFixed(2)
  };
}

function recalculateOfferValue() {
  const rrp = Number(rrpInput.value);
  const margin = Number(marginInput.value);

  if (isNaN(rrp) || isNaN(margin)) {
    offerInput.value = '';
    return;
  }

  const offer = rrp * (1 - margin / 100);
  offerInput.value = offer.toFixed(0);
}

function resetEbayAnalysis() {
  document.getElementById('ebay-min').textContent = '-';
  document.getElementById('ebay-avg').textContent = '-';
  document.getElementById('ebay-median').textContent = '-';
  document.getElementById('ebay-mode').textContent = '-';

  const rrpEl = document.getElementById('ebaySuggestedRrp');
  const marginEl = document.getElementById('ebayMinMargin');
  const offerEl = document.getElementById('ebayOfferValue');

  if (rrpEl) rrpEl.value = '';
  if (marginEl) marginEl.value = '';
  if (offerEl) offerEl.value = '';

  const analysisWrapper = document.querySelector('.ebay-analysis-wrapper');
  if (analysisWrapper) {
    analysisWrapper.style.display = 'none';
  }
}

// ============================================
// STATE MANAGEMENT
// ============================================

function saveEbayWizardState() {
  window.wizardState.ebay = {
    searchTerm: ebaySearchInput.value.trim(),
    filters: JSON.parse(JSON.stringify(selectedFilters)),
    topFilters: {
      sold: filterSoldCheckbox.checked,
      ukOnly: filterUKCheckbox.checked,
      used: filterUsedCheckbox.checked
    },
    prices: {
      min: document.getElementById('ebay-min')?.textContent,
      avg: document.getElementById('ebay-avg')?.textContent,
      median: document.getElementById('ebay-median')?.textContent,
      mode: document.getElementById('ebay-mode')?.textContent
    },
    selectedOffer: offerInput.value,
    suggestedPriceMethod: 'Average Price',
    rrp: rrpInput.value,
    margin: marginInput.value,
    listings: window.currentEbayResults || [],
    uiState: {
      expandedSections: Array.from(
        ebayFiltersContainer.querySelectorAll('.ebay-filter-section.expanded h4')
      ).map(h4 => h4.textContent.trim()),
      filterScroll: ebayFiltersContainer.scrollTop,
      resultsScroll: ebayResultsContainer.scrollTop
    }
  };
}

function restoreEbayWizardState() {
  const state = window.wizardState.ebay;
  if (!state) return;

  ebaySearchInput.value = state.searchTerm || '';
  selectedFilters = state.filters || {};
  filterSoldCheckbox.checked = state.topFilters?.sold || false;
  filterUKCheckbox.checked = state.topFilters?.ukOnly || false;
  filterUsedCheckbox.checked = state.topFilters?.used || false;

  // Only auto-run if we have no results yet
  if (!state.listings || !state.listings.length && window.wizardState.ebay?.searchTerm) {
    ebayWizardStep = 1;
    ebayWizardBtn.textContent = 'Next';
    ebayWizardBtn.click();
    console.log("clicking search");
  }

  // Restore stats and pricing
  document.getElementById('ebay-min').textContent = state.prices?.min ?? '-';
  document.getElementById('ebay-avg').textContent = state.prices?.avg ?? '-';
  document.getElementById('ebay-median').textContent = state.prices?.median ?? '-';
  document.getElementById('ebay-mode').textContent = state.prices?.mode ?? '-';

  rrpInput.value = state.rrp || '';
  marginInput.value = state.margin || '';
  offerInput.value = state.selectedOffer || '';

  if (state.listings?.length) {

    window.currentEbayResults = state.listings;

    const rawPrices = state.listings
      .map(item => Number(item.price))
      .filter(p => !isNaN(p) && p > 0);

    const cleanedPrices = removeOutliers(rawPrices);
    window._ebayPriceCache = { rawPrices, cleanedPrices };

    renderResults(state.listings);

    if (!document.getElementById('ebayShowAnomalies')?.checked) {
      document
        .querySelectorAll('.ebay-listing-card[data-anomalous="true"]')
        .forEach(card => card.style.display = 'none');
    }

  }

  // Restore UI state
  if (state.uiState) {
    state.uiState.expandedSections?.forEach(sectionName => {
      const section = Array.from(ebayFiltersContainer.querySelectorAll('.ebay-filter-section'))
        .find(s => s.querySelector('h4')?.textContent.trim() === sectionName);
      if (section) section.classList.add('expanded');
    });
    ebayFiltersContainer.scrollTop = state.uiState.filterScroll || 0;
    ebayResultsContainer.scrollTop = state.uiState.resultsScroll || 0;
  }
}

function setEbayScrapingState(isScraping) {
  isEbayScraping = isScraping;

  // Toggle the wizard button instead of the Apply button
  ebayWizardBtn.disabled = isScraping;
  ebayWizardBtn.classList.toggle('disabled', isScraping);

  ebayWizardBtn.textContent = isScraping
    ? 'Scraping...'
    : (ebayWizardStep === 1 ? 'Next' : 'Search');
}

// Wait until the DOM is fully loaded
document.addEventListener('DOMContentLoaded', () => {
  const completeBtn = document.getElementById('ebayApplyBtn');

  completeBtn?.addEventListener('click', () => {
    // Make sure your ResearchWizard exists
    if (window.ResearchWizard && typeof window.ResearchWizard.showOverview === 'function') {
      window.ResearchWizard.showOverview();
    } else {
      console.warn('ResearchWizard.showOverview is not defined.');
    }
  });
});
