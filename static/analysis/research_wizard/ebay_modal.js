// eBay Modal Logic
const scrapeEbayBtn = document.getElementById('scrapeEbayBtn');
const ebayModal = document.getElementById('ebayModal');
// const closeEbayModal = document.getElementById('closeEbayModal');
const ebaySearchInput = document.getElementById('ebaySearchInput');
const ebaySearchBtn = document.getElementById('ebaySearchBtn');
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


let selectedFilters = {};
let isEbayScraping = false;
let previousSelectedFilters = {};


// Open modal
scrapeEbayBtn.addEventListener('click', () => {
  ebayModal.classList.add('active');
  ebaySearchInput.focus();
});



function setEbayScrapingState(isScraping) {
  isEbayScraping = isScraping;

  ebayApplyBtn.disabled = isScraping;
  ebayApplyBtn.classList.toggle('disabled', isScraping);

  ebayApplyBtn.textContent = isScraping
    ? 'Scraping...'
    : 'Apply';
}


// Handle search - fetch filters
ebaySearchBtn.addEventListener('click', async () => {
  resetEbayAnalysis();
  const searchTerm = ebaySearchInput.value.trim();

  if (!searchTerm) {
    alert('Please enter a search term');
    return;
  }

  ebayFiltersContainer.innerHTML =
    '<div style="text-align: center; padding: 20px; color: #666;">Loading filters...</div>';
  ebayFiltersContainer.style.display = 'block';
  ebayResultsContainer.style.display = 'none';

  try {
    const response = await fetch(
        `/api/ebay/filters/?q=${encodeURIComponent(searchTerm)}`,
        {
          method: "GET",
          headers: {
            "Accept": "application/json"
          }
        }
      );

      if (!response.ok) {
        throw new Error("Failed to fetch eBay filters");
      }

      const data = await response.json();

      // Expecting: { success: true, filters: [...] }
      renderFilters(data.filters);

  } catch (error) {
    console.error('Error fetching filters:', error);
    ebayFiltersContainer.innerHTML =
      '<div style="text-align: center; padding: 20px; color: #c00;">Error loading filters. Please try again.</div>';
  }
});


function renderFilters(filters, restoreFilters = null) {
  selectedFilters = {};
  updateSelectedCount();
  
  ebayFiltersContainer.innerHTML = filters.map(filter => {
    if (filter.type === 'checkbox') {

      // ✅ Sort options by count (descending)
      const sortedOptions = [...filter.options].sort((a, b) => {
        const countA = a.count ?? 0;
        const countB = b.count ?? 0;
        return countB - countA;
      });


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

    // 🔁 Restore selections if provided
  if (restoreFilters) {
    restoreFilterSelections(restoreFilters);
  }

}

function restoreFilterSelections(restoreFilters) {
  Object.entries(restoreFilters).forEach(([filterName, value]) => {

    // CHECKBOX FILTERS
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

    // RANGE FILTERS
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
  const filterName = e.target.dataset.filter; // This will now be the name
  
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


// TODO: I guess this should be in the backend not the frontend
// Build eBay search URL from selected filters
function buildEbayUrl(searchTerm, filters) {
  const baseUrl = "https://www.ebay.co.uk/sch/i.html";
  
  const params = {
    "_nkw": searchTerm.replace(/ /g, '+'),
    "_sacat": "0",
    "_from": "R40",
    "_dcat": "9355"
  };

  // Add filters with double-encoding
  Object.entries(filters).forEach(([filterName, value]) => {
    if (Array.isArray(value)) {
      // Double-encode: first encode, then encode again
      const doubleEncodedKey = encodeURIComponent(encodeURIComponent(filterName));
      const doubleEncodedValue = value
        .map(v => encodeURIComponent(encodeURIComponent(v)))
        .join("|");
      params[doubleEncodedKey] = doubleEncodedValue;
    } else if (typeof value === 'object') {
      const doubleEncodedKey = encodeURIComponent(encodeURIComponent(filterName));
      if (value.min) params[`${doubleEncodedKey}_min`] = encodeURIComponent(encodeURIComponent(value.min));
      if (value.max) params[`${doubleEncodedKey}_max`] = encodeURIComponent(encodeURIComponent(value.max));
    } else {
      const doubleEncodedKey = encodeURIComponent(encodeURIComponent(filterName));
      params[doubleEncodedKey] = encodeURIComponent(encodeURIComponent(value));
    }
  });

  // Build query string without additional encoding
  const queryString = Object.entries(params)
    .map(([key, value]) => `${key}=${value}`)
    .join('&');

  return `${baseUrl}?${queryString}`;
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

// eBay back button
document.querySelector('.rw-back-ebay')?.addEventListener('click', () => {
  window.ResearchWizard.showSourcePage();
});


// Handle apply button
ebayApplyBtn.addEventListener('click', async () => {

  if (isEbayScraping) return;
  resetEbayAnalysis(); 

  const searchTerm = ebaySearchInput.value.trim();
  
  if (!searchTerm) {
    alert('Please enter a search term');
    return; // button never gets disabled
  }

  setEbayScrapingState(true); // now safe to disable


  // ✅ READ TOP FILTERS
  const ebayFilterSold = filterSoldCheckbox.checked;
  const ebayFilterUKOnly = filterUKCheckbox.checked;
  const ebayFilterUsed = filterUsedCheckbox.checked;

  
  console.log('Applying eBay search with filters:', {
    searchTerm,
    filters: selectedFilters
  });
  
  // Show loading in results area
  ebayResultsContainer.style.display = 'block';
  ebayResultsContainer.innerHTML = '<div style="text-align: center; padding: 40px; color: #666;">Scraping eBay listings...</div>';
            
  try {
    // 🔒 Snapshot selected filters BEFORE scraping
    previousSelectedFilters = JSON.parse(JSON.stringify(selectedFilters));

    // TODO: THIS FUNCITON IS REALLY WEIRD BECAUSE IT BUILDS EVERYTHING EXCEPT THE TOP FILTERS
    const ebayUrl = buildEbayUrl(searchTerm, selectedFilters);
    console.log("eBay URL to scrape:", ebayUrl);

    const response = await sendExtensionMessage({
      action: "scrape",
      data: {
        directUrl: ebayUrl,
        competitors: ["eBay"],
        ebayFilterSold: ebayFilterSold,
        ebayFilterUsed: ebayFilterUsed,
        ebayFilterUKOnly: ebayFilterUKOnly,
      }
    });

    if (response.success) {
      console.log("Scraping success", response.results);
      renderResults(response.results);
      // Extract numeric prices safely
      const prices = response.results
        .map(item => Number(item.price))
        .filter(p => !isNaN(p) && p > 0);

      const stats = calculateStats(prices);

      // Populate analysis table
      document.getElementById('ebay-min').textContent = stats.min;
      document.getElementById('ebay-avg').textContent = stats.avg;
      document.getElementById('ebay-median').textContent = stats.median;
      document.getElementById('ebay-mode').textContent = stats.mode;

      // Ensure table is visible
      document.querySelector('.ebay-analysis-wrapper').style.display = 'block';

      // ===== SUGGESTED RRP =====
      let suggestedRrp = null;

      const medianNum = Number(stats.median);

      if (!isNaN(medianNum)) {
        let rounded = Math.round(medianNum);
        suggestedRrp = (rounded % 2 === 0) ? rounded - 2 : rounded - 1;
        if (suggestedRrp < 0) suggestedRrp = 0;
      }

      const rrpEl = document.getElementById('ebaySuggestedRrp');
      if (rrpEl && suggestedRrp !== null) {
        rrpEl.value = suggestedRrp.toFixed(0);
      }

      if (marginInput && !marginInput.value) {
        marginInput.value = 50; // default 20% margin
        recalculateOfferValue();
      }


      // REFRESH FILTERS BASED ON REAL URL
      refreshFiltersFromUrl(ebayUrl);
    } else {
      alert("Scraping failed: " + (response.error || "Unknown error"));
    }

  } catch (error) {
    console.error("Scraping error:", error);
    alert("Error running scraper: " + error.message);
  } finally {
    // ✅ GUARANTEED UNLOCK
    setEbayScrapingState(false);
  }
});

function resetEbayAnalysis() {
  document.getElementById('ebay-min').textContent = '-';
  document.getElementById('ebay-avg').textContent = '-';
  document.getElementById('ebay-median').textContent = '-';
  document.getElementById('ebay-mode').textContent = '-';

  // Reset pricing inputs
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

rrpInput.addEventListener('input', recalculateOfferValue);
marginInput.addEventListener('input', recalculateOfferValue);


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



function getMockResults() {
  return {
    summary: {
      ebay_min: '£295.00',
      ebay_avg: '£368.75',
      ebay_mode: '£365.00',
      ebay_median: '£370.00'
    },
    listings: [
      {
        title: 'iPhone 13 Pro 128GB Graphite - Unlocked',
        price: '£365.00',
        condition: 'Used',
        seller: 'tech_store_uk',
        url: '#',
        image: 'https://via.placeholder.com/80'
      },
      {
        title: 'Apple iPhone 13 Pro 128GB Sierra Blue',
        price: '£370.00',
        condition: 'Used',
        seller: 'mobile_deals',
        url: '#',
        image: 'https://via.placeholder.com/80'
      },
      {
        title: 'iPhone 13 Pro 128GB Gold - Good Condition',
        price: '£355.00',
        condition: 'Used',
        seller: 'phone_reseller',
        url: '#',
        image: 'https://via.placeholder.com/80'
      },
      {
        title: 'iPhone 13 Pro 128GB Silver Unlocked',
        price: '£380.00',
        condition: 'Used',
        seller: 'electronics_hub',
        url: '#',
        image: 'https://via.placeholder.com/80'
      },
      {
        title: 'Apple iPhone 13 Pro 128GB - Excellent',
        price: '£375.00',
        condition: 'Used',
        seller: 'premium_phones',
        url: '#',
        image: 'https://via.placeholder.com/80'
      }
    ]
  };
}

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
      <h3>eBay Listings (${results.length} results)</h3>
    </div>

    <div class="ebay-listings">
      ${results.map(item => `
        <div class="ebay-listing-card" style="display:flex; gap:15px; padding:12px;">
          
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

  // Sort prices numerically
  const sorted = [...prices].sort((a, b) => a - b);

  // MIN
  const min = sorted[0];

  // AVERAGE
  const avg = sorted.reduce((sum, p) => sum + p, 0) / sorted.length;

  // MEDIAN
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0
      ? (sorted[mid - 1] + sorted[mid]) / 2
      : sorted[mid];

  // MODE
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


// Handle cancel button
ebayCancelBtn.addEventListener('click', () => {
  closeModal();
});

// Enter key to search
ebaySearchInput.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') {
    ebaySearchBtn.click();
  }
});