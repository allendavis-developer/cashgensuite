// ============================================
// DOM ELEMENT REFERENCES
// ============================================

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
const ebayShowHistogramCheckbox = document.getElementById('ebayShowHistogram');
const rrpDisplay = document.getElementById('ebaySuggestedRrp');
const offerDisplay = document.getElementById('ebayOfferValue');

// Store numeric values for wizard state (not formatted strings)
let ebayRrpNumeric = null;
let ebayOfferNumeric = null;

// ============================================
// STATE VARIABLES
// ============================================

let selectedFilters = {};
let previousSelectedFilters = {};
let isEbayScraping = false;
let ebayWizardStep = 1; // 1 = fetch filters, 2 = ready to search
// Flag to prevent sync loops - use window property to avoid duplicate declaration errors
window.ebayIsSyncingCategory = window.ebayIsSyncingCategory || false;

// ============================================
// EVENT LISTENERS
// ============================================


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
    
    // If N/A is selected, category should be null/empty
    const category = (categoryInputValue === 'na' || categoryText === 'N/A') 
      ? null 
      : categoryText.toLowerCase(); // lowercase for mapping
    
    // Build the options object for buildEbayUrl
    const options = {
        category: category,
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

          // Filter to valid listings with prices
          const validListings = listings.filter(item => {
            const price = Number(item.price);
            return !isNaN(price) && price > 0;
          });

          // Store only raw listings - everything else can be derived
          window._ebayPriceCache = { 
            rawListings: validListings
          };

          // Derive cleaned listings for anomaly detection
          const cleanedListings = removeOutliers(validListings);
          const cleanedPrices = cleanedListings.map(item => Number(item.price));
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

          const stats = calculateStats(cleanedListings);
          document.getElementById('ebay-min').textContent = stats.min;
          document.getElementById('ebay-avg').textContent = stats.avg;
          document.getElementById('ebay-median').textContent = stats.median;
          document.getElementById('ebay-mode').textContent = stats.mode;

          // Render histogram only if checkbox is checked
          if (ebayShowHistogramCheckbox?.checked) {
            renderHistogram(cleanedListings);
          }

          // Show the analysis wrapper after successful scraping
          const analysisWrapper = document.querySelector('.ebay-analysis-wrapper');
          if (analysisWrapper) {
            analysisWrapper.style.display = 'block';
          }

          // Suggested RRP and Offer (40% of intelligent average)
          const intelligentAvg = calculateIntelligentAverage(cleanedListings);
          const normalAvg = Number(stats.avg);
          const avgNum = intelligentAvg !== null ? intelligentAvg : normalAvg;
          
          console.log('=== eBay Average Calculation ===');
          console.log('Normal average (table):', normalAvg);
          console.log('Intelligent average:', intelligentAvg);
          console.log('Using for RRP:', avgNum);
          console.log('RRP value:', Math.round(avgNum));
          console.log('Listings count:', cleanedListings.length);
          console.log('Listings with sold dates:', cleanedListings.filter(item => parseSoldDate(item.sold)).length);
          
          if (!isNaN(avgNum)) {
              const rrp = Math.round(avgNum);
              const offer = Math.round(avgNum * 0.4);
              // Store numeric values for wizard state
              ebayRrpNumeric = rrp;
              ebayOfferNumeric = offer;
              // Display formatted values
              rrpDisplay.textContent = rrp.toLocaleString();
              offerDisplay.textContent = offer.toLocaleString();
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

// No event listeners needed for display-only values

// Back button
document.querySelector('.rw-back-ebay')?.addEventListener('click', () => {
  saveEbayWizardState();
  window.ResearchWizard.showOverview();
});

document.getElementById('ebayShowAnomalies')?.addEventListener('change', e => {
  const cache = window._ebayPriceCache;
  if (!cache || !cache.rawListings) return;

  // Derive cleaned listings from raw listings
  const cleanedListings = removeOutliers(cache.rawListings);
  const listings = document.getElementById('ebayShowAnomalies').checked
    ? cache.rawListings
    : cleanedListings;

  const stats = calculateStats(listings);

  document.getElementById('ebay-min').textContent = stats.min;
  document.getElementById('ebay-avg').textContent = stats.avg;
  document.getElementById('ebay-median').textContent = stats.median;
  document.getElementById('ebay-mode').textContent = stats.mode;

  // Update histogram if visible
  if (ebayShowHistogramCheckbox?.checked) {
    renderHistogram(listings);
  }

  // Update RRP based on intelligent average, Offer is 40% of intelligent average
  const intelligentAvg = calculateIntelligentAverage(listings);
  const normalAvg = Number(stats.avg);
  const avgNum = intelligentAvg !== null ? intelligentAvg : normalAvg;
  
  console.log('=== eBay Average Calculation (Anomalies Toggle) ===');
  console.log('Normal average (table):', normalAvg);
  console.log('Intelligent average:', intelligentAvg);
  console.log('Using for RRP:', avgNum);
  console.log('RRP value:', Math.round(avgNum));
  
  if (!isNaN(avgNum)) {
    const rrp = Math.round(avgNum);
    const offer = Math.round(avgNum * 0.4);
    // Store numeric values for wizard state
    ebayRrpNumeric = rrp;
    ebayOfferNumeric = offer;
    // Display formatted values
    rrpDisplay.textContent = rrp.toLocaleString();
    offerDisplay.textContent = offer.toLocaleString();
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

// Histogram visibility toggle
ebayShowHistogramCheckbox?.addEventListener('change', e => {
  const histogramContainer = document.getElementById('ebayHistogramContainer');
  if (!histogramContainer) return;
  
  if (e.target.checked) {
    // Show histogram - need to render it if we have data
    const cache = window._ebayPriceCache;
    if (cache && cache.rawListings) {
      const showAnomalies = document.getElementById('ebayShowAnomalies')?.checked ?? true;
      const listings = showAnomalies ? cache.rawListings : removeOutliers(cache.rawListings);
      renderHistogram(listings);
    }
    histogramContainer.style.display = 'block';
  } else {
    histogramContainer.style.display = 'none';
  }
  
  saveEbayWizardState();
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
  
  // Update count display if element exists (may have been removed from UI)
  if (ebaySelectedCount) {
    ebaySelectedCount.textContent = count;
  }
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
// Button is always visible, but disabled until results exist
ebayApplyBtn.disabled = true;
ebayApplyBtn.classList.add('disabled');


function renderResults(results) {
  if (!results || results.length === 0) {
    ebayResultsContainer.innerHTML = `
      <div style="text-align:center; padding:40px; color:#666;">
        No eBay listings found.
      </div>
    `;
    // Disable the Complete button when there are no results
    ebayApplyBtn.disabled = true;
    ebayApplyBtn.classList.add('disabled');
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

            <div class="ebay-listing-price">
              £${Number(item.price).toFixed(2)}
            </div>

            ${item.sold ? `
              <div class="ebay-listing-sold">
                ${item.sold}
              </div>
            ` : ""}

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

/**
 * Parse sold date from text like "Sold 12 Jan 2026"
 * Returns Date object or null if parsing fails
 */
function parseSoldDate(soldText) {
  if (!soldText || typeof soldText !== 'string') return null;
  
  // Remove "Sold" prefix and trim
  const dateStr = soldText.replace(/^Sold\s+/i, '').trim();
  if (!dateStr) return null;
  
  // Try to parse the date
  // Format: "12 Jan 2026" or "12 January 2026"
  const months = {
    'jan': 0, 'january': 0,
    'feb': 1, 'february': 1,
    'mar': 2, 'march': 2,
    'apr': 3, 'april': 3,
    'may': 4,
    'jun': 5, 'june': 5,
    'jul': 6, 'july': 6,
    'aug': 7, 'august': 7,
    'sep': 8, 'september': 8,
    'oct': 9, 'october': 9,
    'nov': 10, 'november': 10,
    'dec': 11, 'december': 11
  };
  
  // Match pattern: day month year
  const match = dateStr.match(/^(\d{1,2})\s+(\w+)\s+(\d{4})$/i);
  if (match) {
    const day = parseInt(match[1], 10);
    const monthName = match[2].toLowerCase();
    const year = parseInt(match[3], 10);
    const month = months[monthName];
    
    if (month !== undefined && day >= 1 && day <= 31) {
      return new Date(year, month, day);
    }
  }
  
  // Fallback: try native Date parsing
  const parsed = new Date(dateStr);
  if (!isNaN(parsed.getTime())) {
    return parsed;
  }
  
  return null;
}

/**
 * Calculate intelligent time-weighted average based on sold dates
 * Implements the algorithm described in the requirements
 */
function calculateIntelligentAverage(listings) {
  // Filter to only listings with valid price and sold date
  const validListings = listings
    .map(item => {
      const price = Number(item.price);
      const soldDate = parseSoldDate(item.sold);
      if (isNaN(price) || price <= 0 || !soldDate) return null;
      return { price, date: soldDate };
    })
    .filter(item => item !== null);
  
  console.log('[calculateIntelligentAverage] Total listings:', listings.length);
  console.log('[calculateIntelligentAverage] Valid listings with sold dates:', validListings.length);
  
  if (validListings.length === 0) {
    console.log('[calculateIntelligentAverage] No valid listings, returning null');
    return null;
  }
  
  const n = validListings.length;
  const now = new Date();
  
  // Case 1: 4+ data points - learn from time
  if (n >= 4) {
    console.log('[calculateIntelligentAverage] Case 1: 4+ data points');
    // Sort by date (oldest first)
    validListings.sort((a, b) => a.date.getTime() - b.date.getTime());
    
    // Calculate time differences in days
    const timeDiffs = [];
    const logPriceDiffs = [];
    
    // Minimum time delta to avoid numerical instability from same-day noise
    // This is a physics/clock constant, not an economic parameter
    const MIN_DT_DAYS = 0.25; // 6 hours - ignore sub-day price jitter
    
    for (let i = 1; i < validListings.length; i++) {
      const dt = (validListings[i].date.getTime() - validListings[i - 1].date.getTime()) / (1000 * 60 * 60 * 24); // days
      // Only consider time deltas above minimum threshold to avoid pathological volatility
      // from same-day sales with small price differences
      if (dt > MIN_DT_DAYS) {
        timeDiffs.push(dt);
        const logDiff = Math.abs(Math.log(validListings[i].price) - Math.log(validListings[i - 1].price));
        logPriceDiffs.push(logDiff / dt);
      }
    }
    
    if (timeDiffs.length === 0) {
      // No time differences, fall back to simple average
      console.log('[calculateIntelligentAverage] No valid time differences, falling back to simple average');
      const sum = validListings.reduce((s, item) => s + item.price, 0);
      const simpleAvg = sum / n;
      console.log('[calculateIntelligentAverage] Simple average:', simpleAvg);
      return simpleAvg;
    }
    
    // Measure observed instability: median of |log(price_i) - log(price_i-1)| / Δt_i
    const sortedInstability = [...logPriceDiffs].sort((a, b) => a - b);
    const mid = Math.floor(sortedInstability.length / 2);
    const v = sortedInstability.length % 2 === 0
      ? (sortedInstability[mid - 1] + sortedInstability[mid]) / 2
      : sortedInstability[mid];
    
    console.log('[calculateIntelligentAverage] Volatility (v):', v);
    console.log('[calculateIntelligentAverage] Valid time deltas:', timeDiffs.length);
    
    // Convert instability into trust weights: w_i = e^(-v * t_i)
    // where t_i is time since sale (in days)
    const weights = validListings.map(item => {
      const daysSinceSale = (now.getTime() - item.date.getTime()) / (1000 * 60 * 60 * 24);
      return Math.exp(-v * daysSinceSale);
    });
    
    console.log('[calculateIntelligentAverage] Weights:', weights);
    
    // Compute weighted average: E = Σ(p_i * w_i) / Σ(w_i)
    const weightedSum = validListings.reduce((sum, item, i) => sum + item.price * weights[i], 0);
    const weightSum = weights.reduce((sum, w) => sum + w, 0);
    
    const result = weightSum > 0 ? weightedSum / weightSum : null;
    console.log('[calculateIntelligentAverage] Weighted average result:', result);
    return result;
  }
  
  // Case 2: 2-3 data points - geometric center with directional trust
  if (n === 2 || n === 3) {
    console.log('[calculateIntelligentAverage] Case 2: 2-3 data points');
    // Work in log space
    const logPrices = validListings.map(item => Math.log(item.price));
    const avgLog = logPrices.reduce((sum, lp) => sum + lp, 0) / n;
    const geometricCenter = Math.exp(avgLog);
    
    // Find newest price
    const newest = validListings.reduce((newest, item) => 
      item.date > newest.date ? item : newest
    );
    
    console.log('[calculateIntelligentAverage] Geometric center:', geometricCenter);
    console.log('[calculateIntelligentAverage] Newest price:', newest.price);
    
    // Apply directional trust
    let result;
    if (newest.price < geometricCenter) {
      // If newest price < G → trust newest
      result = newest.price;
      console.log('[calculateIntelligentAverage] Newest < G, using newest:', result);
    } else {
      // Else → split between G and newest
      result = (geometricCenter + newest.price) / 2;
      console.log('[calculateIntelligentAverage] Newest >= G, using average:', result);
    }
    return result;
  }
  
  // Case 3: 1 data point - pure observation
  console.log('[calculateIntelligentAverage] Case 3: 1 data point');
  const result = validListings[0].price;
  console.log('[calculateIntelligentAverage] Single price:', result);
  return result;
}

function removeOutliers(listings) {
  // Extract prices for outlier removal
  const prices = listings
    .map(item => Number(item.price))
    .filter(p => !isNaN(p) && p > 0);
  
  if (prices.length < 4) return listings;

  // --- Step 0: keep only valid positive prices
  const valid = prices.filter(p => p > 0);
  if (valid.length < 4) return listings;

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
    const priceSet = new Set(semanticFiltered);
    return listings.filter(item => priceSet.has(Number(item.price)));
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

  const validPrices = new Set(
    pairs
      .filter(p => p.log >= lowerBound && p.log <= upperBound)
      .map(p => p.price)
  );
  
  return listings.filter(item => validPrices.has(Number(item.price)));
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
    // Prevent sync loops
    if (window.ebayIsSyncingCategory) return;
    
    if (!value) return;

    const option = ebayCategoryTomSelect.options[value];

    // Persist to wizard state
    window.wizardState.ebay = window.wizardState.ebay || {};
    
    // If N/A is selected, set category to null
    if (value === 'na') {
      window.wizardState.ebay.category = null;
      
      // Also set CeX category to null
      if (!window.wizardState.cex) {
        window.wizardState.cex = {};
      }
      window.wizardState.cex.category = null;
      
      console.log('eBay category set to N/A (null)');
      return;
    }

    const categoryData = {
      id: value,
      name: option?.text || null
    };
    window.wizardState.ebay.category = categoryData;

    // Sync to CeX category in wizardState
    if (!window.wizardState.cex) {
      window.wizardState.cex = {};
    }
    window.wizardState.cex.category = categoryData;

    // Sync CeX TomSelect if it exists and is initialized
    if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
      // Check if the category exists in CeX categories and isn't already selected
      const cexCategoryExists = categoryTomSelect.options[value];
      const currentCexValue = categoryTomSelect.getValue();
      if (cexCategoryExists && currentCexValue !== value) {
        window.ebayIsSyncingCategory = true;
        categoryTomSelect.setValue(value);
        // Reset flag after a short delay to allow the change event to process
        setTimeout(() => { window.ebayIsSyncingCategory = false; }, 100);
      }
    }

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

  // Add N/A option first (auto-selected)
  ebayCategoryTomSelect.addOption({
    value: 'na',
    text: 'N/A'
  });

  ebayCategoryCache.categories.forEach(cat => {
    ebayCategoryTomSelect.addOption({
      value: cat.id,
      text: cat.name
    });
  });

  ebayCategoryTomSelect.refreshOptions(false);
  
  // Auto-select N/A
  ebayCategoryTomSelect.setValue('na');
}


/**
 * Calculate optimal bin width for histogram using Freedman-Diaconis rule
 * Falls back to Sturges' rule for small datasets
 */
function calculateBinWidth(prices) {
  if (!prices || prices.length < 2) return 10; // Default fallback
  
  const sorted = [...prices].sort((a, b) => a - b);
  const n = sorted.length;
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const range = max - min;
  
  if (range === 0) return 10; // All prices are the same
  
  // Calculate IQR for Freedman-Diaconis rule
  const q1Index = Math.floor(n * 0.25);
  const q3Index = Math.floor(n * 0.75);
  const q1 = sorted[q1Index];
  const q3 = sorted[q3Index];
  const iqr = q3 - q1;
  
  let binWidth;
  
  if (iqr > 0 && n >= 4) {
    // Freedman-Diaconis rule: bin width = 2 * IQR / n^(1/3)
    binWidth = (2 * iqr) / Math.pow(n, 1/3);
  } else {
    // Sturges' rule fallback: number of bins = 1 + log2(n), then bin width = range / bins
    const numBins = Math.ceil(1 + Math.log2(n));
    binWidth = range / numBins;
  }
  
  // Round to a nice number for readability
  // Round to nearest 5, 10, 25, 50, 100, etc. based on magnitude
  const magnitude = Math.pow(10, Math.floor(Math.log10(binWidth)));
  const normalized = binWidth / magnitude;
  
  let rounded;
  if (normalized <= 1) rounded = 1;
  else if (normalized <= 2) rounded = 2;
  else if (normalized <= 5) rounded = 5;
  else rounded = 10;
  
  binWidth = rounded * magnitude;
  
  // Ensure minimum bin width of 1
  return Math.max(1, binWidth);
}

/**
 * Generate histogram data (bins and frequencies) from price data
 */
function generateHistogramData(listings) {
  const prices = listings
    .map(item => Number(item.price))
    .filter(p => !isNaN(p) && p > 0);
  
  if (!prices.length) {
    return { bins: [], frequencies: [], binWidth: 0 };
  }
  
  const sorted = [...prices].sort((a, b) => a - b);
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const binWidth = calculateBinWidth(prices);
  
  // Create bins
  const bins = [];
  const frequencies = [];
  
  // Start from a rounded-down value
  const startBin = Math.floor(min / binWidth) * binWidth;
  const endBin = Math.ceil(max / binWidth) * binWidth;
  
  // Initialize bins
  for (let binStart = startBin; binStart < endBin; binStart += binWidth) {
    const binEnd = binStart + binWidth;
    bins.push({ start: binStart, end: binEnd });
    frequencies.push(0);
  }
  
  // Count frequencies
  prices.forEach(price => {
    const binIndex = Math.floor((price - startBin) / binWidth);
    // Handle edge case where price equals the last bin's end
    const actualIndex = binIndex >= frequencies.length ? frequencies.length - 1 : binIndex;
    if (actualIndex >= 0 && actualIndex < frequencies.length) {
      frequencies[actualIndex]++;
    }
  });
  
  return { bins, frequencies, binWidth };
}

/**
 * Render histogram visualization
 */
function renderHistogram(listings) {
  const histogramContainer = document.getElementById('ebayHistogramContainer');
  if (!histogramContainer) return;
  
  const histogramData = generateHistogramData(listings);
  
  if (!histogramData.bins.length) {
    histogramContainer.innerHTML = '<div class="ebay-histogram-empty">No price data available</div>';
    return;
  }
  
  const maxFrequency = Math.max(...histogramData.frequencies);
  const maxBarHeight = 200; // pixels
  const numBins = histogramData.bins.length;
  const shouldRotateLabels = numBins > 8; // Rotate labels if too many bins
  
  histogramContainer.innerHTML = `
    <div class="ebay-histogram-header">
      <h4>Price Distribution</h4>
      <span class="ebay-histogram-info">Bin width: £${histogramData.binWidth.toFixed(2)}</span>
    </div>
    <div class="ebay-histogram-chart ${shouldRotateLabels ? 'rotated-labels' : ''}">
      ${histogramData.bins.map((bin, index) => {
        const frequency = histogramData.frequencies[index];
        const height = maxFrequency > 0 ? (frequency / maxFrequency) * maxBarHeight : 0;
        const binLabel = `£${bin.start.toFixed(0)}-£${bin.end.toFixed(0)}`;
        const labelText = bin.start.toFixed(0);
        
        return `
          <div class="ebay-histogram-bar-container" title="${binLabel}: ${frequency} listing${frequency !== 1 ? 's' : ''}">
            <div class="ebay-histogram-bar" style="height: ${height}px;">
              ${frequency > 0 ? `<span class="ebay-histogram-frequency">${frequency}</span>` : ''}
            </div>
            <div class="ebay-histogram-label ${shouldRotateLabels ? 'rotated' : ''}">${labelText}</div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function calculateStats(listings) {
  // Extract prices from listings
  const prices = listings
    .map(item => Number(item.price))
    .filter(p => !isNaN(p) && p > 0);
  
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

  // Normal arithmetic average (for display in stats table)
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

// Offer is always 40% of average, no recalculation needed

function resetEbayAnalysis() {
  document.getElementById('ebay-min').textContent = '-';
  document.getElementById('ebay-avg').textContent = '-';
  document.getElementById('ebay-median').textContent = '-';
  document.getElementById('ebay-mode').textContent = '-';

  if (rrpDisplay) rrpDisplay.textContent = '--';
  if (offerDisplay) offerDisplay.textContent = '--';
  
  // Reset numeric values
  ebayRrpNumeric = null;
  ebayOfferNumeric = null;

  const analysisWrapper = document.querySelector('.ebay-analysis-wrapper');
  if (analysisWrapper) {
    analysisWrapper.style.display = 'none';
  }

  // Clear and hide histogram
  const histogramContainer = document.getElementById('ebayHistogramContainer');
  if (histogramContainer) {
    histogramContainer.innerHTML = '';
    histogramContainer.style.display = 'none';
  }
  
  // Uncheck histogram checkbox
  if (ebayShowHistogramCheckbox) {
    ebayShowHistogramCheckbox.checked = false;
  }

  // Disable the Complete button when resetting
  ebayApplyBtn.disabled = true;
  ebayApplyBtn.classList.add('disabled');
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
    // Persist currently selected category (if any) from the TomSelect control
    category: window.wizardState.ebay?.category || null,
    prices: {
      min: document.getElementById('ebay-min')?.textContent,
      avg: document.getElementById('ebay-avg')?.textContent,
      median: document.getElementById('ebay-median')?.textContent,
      mode: document.getElementById('ebay-mode')?.textContent
    },
    selectedOffer: ebayOfferNumeric ?? (offerDisplay?.textContent ? parseFloat(offerDisplay.textContent.replace(/,/g, '')) : null),
    suggestedPriceMethod: 'Average Price',
    rrp: ebayRrpNumeric ?? (rrpDisplay?.textContent ? parseFloat(rrpDisplay.textContent.replace(/,/g, '')) : null),
    listings: window.currentEbayResults || [],
    showAnomalies: document.getElementById('ebayShowAnomalies')?.checked ?? true,
    showHistogram: ebayShowHistogramCheckbox?.checked ?? false,
    uiState: {
      expandedSections: Array.from(
        ebayFiltersContainer.querySelectorAll('.ebay-filter-section.expanded h4')
      ).map(h4 => h4.textContent.trim()),
      filterScroll: ebayFiltersContainer.scrollTop,
      resultsScroll: ebayResultsContainer.scrollTop
    }
  };
}

// Expose globally for use in research_wizard.js
window.restoreEbayWizardState = function restoreEbayWizardState() {
  const state = window.wizardState.ebay;
  if (!state) return;

  ebaySearchInput.value = state.searchTerm || '';
  selectedFilters = state.filters || {};
  filterSoldCheckbox.checked = state.topFilters?.sold || false;
  filterUKCheckbox.checked = state.topFilters?.ukOnly || false;
  filterUsedCheckbox.checked = state.topFilters?.used || false;
  
  // Restore anomalies checkbox (default to checked if not saved)
  const anomaliesCheckbox = document.getElementById('ebayShowAnomalies');
  if (anomaliesCheckbox) {
    anomaliesCheckbox.checked = state.showAnomalies !== undefined ? state.showAnomalies : true;
  }
  
  // Restore histogram checkbox (default to unchecked)
  if (ebayShowHistogramCheckbox) {
    ebayShowHistogramCheckbox.checked = state.showHistogram ?? false;
  }

  // Restore category from either ebay.category or cex.category (they should be synced)
  const category = state.category || window.wizardState.cex?.category;
  if (ebayCategoryTomSelect) {
    if (!category || !category.id) {
      // No category or null category means N/A
      window.ebayIsSyncingCategory = true;
      ebayCategoryTomSelect.setValue('na');
      setTimeout(() => { window.ebayIsSyncingCategory = false; }, 100);
      
      // Ensure both are synced in wizard state
      if (!window.wizardState.cex) window.wizardState.cex = {};
      window.wizardState.cex.category = null;
      window.wizardState.ebay.category = null;
    } else {
      // Check if category exists in the dropdown
      const categoryExists = ebayCategoryTomSelect.options[category.id];
      if (categoryExists) {
        window.ebayIsSyncingCategory = true;
        ebayCategoryTomSelect.setValue(category.id);
        setTimeout(() => { window.ebayIsSyncingCategory = false; }, 100);
      } else if (category.name) {
        // Category might not be loaded yet, add it
        ebayCategoryTomSelect.addOption({ value: category.id, text: category.name });
        ebayCategoryTomSelect.refreshOptions(false);
        window.ebayIsSyncingCategory = true;
        ebayCategoryTomSelect.setValue(category.id);
        setTimeout(() => { window.ebayIsSyncingCategory = false; }, 100);
      }
      
      // Ensure both are synced in wizard state
      if (!window.wizardState.cex) window.wizardState.cex = {};
      window.wizardState.cex.category = category;
      window.wizardState.ebay.category = category;
    }
  }

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

  // Restore numeric values
  if (state.rrp != null) {
    ebayRrpNumeric = typeof state.rrp === 'number' ? state.rrp : parseFloat(String(state.rrp).replace(/,/g, ''));
    rrpDisplay.textContent = isNaN(ebayRrpNumeric) ? '--' : ebayRrpNumeric.toLocaleString();
  } else {
    ebayRrpNumeric = null;
    if (rrpDisplay) rrpDisplay.textContent = '--';
  }
  
  if (state.selectedOffer != null) {
    ebayOfferNumeric = typeof state.selectedOffer === 'number' ? state.selectedOffer : parseFloat(String(state.selectedOffer).replace(/,/g, ''));
    offerDisplay.textContent = isNaN(ebayOfferNumeric) ? '--' : ebayOfferNumeric.toLocaleString();
  } else {
    ebayOfferNumeric = null;
    if (offerDisplay) offerDisplay.textContent = '--';
  }

  if (state.listings?.length) {
    // Show the analysis wrapper when restoring state with results
    const analysisWrapper = document.querySelector('.ebay-analysis-wrapper');
    if (analysisWrapper) {
      analysisWrapper.style.display = 'block';
    }

    window.currentEbayResults = state.listings;

    // Filter to valid listings with prices
    const validListings = state.listings.filter(item => {
      const price = Number(item.price);
      return !isNaN(price) && price > 0;
    });

    // Store only raw listings - everything else can be derived
    window._ebayPriceCache = { 
      rawListings: validListings
    };

    // Derive cleaned listings for anomaly detection
    const cleanedListings = removeOutliers(validListings);
    const cleanedPrices = cleanedListings.map(item => Number(item.price));
    const cleanedSet = new Set(
      cleanedPrices.map(p => Number(p.toFixed(2)))
    );

    state.listings.forEach(item => {
      const price = Number(Number(item.price).toFixed(2));
      item.isAnomalous = !cleanedSet.has(price);
    });

    renderResults(state.listings);

    if (!document.getElementById('ebayShowAnomalies')?.checked) {
      document
        .querySelectorAll('.ebay-listing-card[data-anomalous="true"]')
        .forEach(card => card.style.display = 'none');
    }

    // Restore histogram visibility and render if enabled
    if (ebayShowHistogramCheckbox) {
      ebayShowHistogramCheckbox.checked = state.showHistogram ?? false;
      const histogramContainer = document.getElementById('ebayHistogramContainer');
      if (histogramContainer) {
        if (ebayShowHistogramCheckbox.checked) {
          const showAnomalies = document.getElementById('ebayShowAnomalies')?.checked ?? true;
          const listingsForHistogram = showAnomalies ? state.listings : removeOutliers(state.listings);
          renderHistogram(listingsForHistogram);
          histogramContainer.style.display = 'block';
        } else {
          histogramContainer.style.display = 'none';
        }
      }
    }

    // Enable the Complete button when restoring state with results
    ebayApplyBtn.disabled = false;
    ebayApplyBtn.classList.remove('disabled');
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
};

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
