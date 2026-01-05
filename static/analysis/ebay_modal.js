// eBay Modal Logic
const scrapeEbayBtn = document.getElementById('scrapeEbayBtn');
const ebayModal = document.getElementById('ebayModal');
const closeEbayModal = document.getElementById('closeEbayModal');
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


let selectedFilters = {};
let isEbayScraping = false;

// Open modal
scrapeEbayBtn.addEventListener('click', () => {
  ebayModal.classList.add('active');
  ebaySearchInput.focus();
});

// Close modal
closeEbayModal.addEventListener('click', () => {
  closeModal();
});

// Close on outside click
ebayModal.addEventListener('click', (e) => {
  if (e.target === ebayModal) {
    closeModal();
  }
});

function closeModal() {
  ebayModal.classList.remove('active');
  ebaySearchInput.value = '';
  ebayFiltersContainer.innerHTML = '';
  ebayFiltersContainer.style.display = 'none';
  ebayResultsContainer.style.display = 'none';
  ebayResultsContainer.innerHTML = '';
  selectedFilters = {};
  updateSelectedCount();
}

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


function renderFilters(filters) {
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
                       data-filter="${filter.id}" 
                       data-value="${option.value}"
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
                   data-filter="${filter.id}" 
                   data-range="min"
                   class="ebay-range-input">
            <span style="margin: 0 8px;">to</span>
            <input type="number" 
                   placeholder="Max" 
                   data-filter="${filter.id}" 
                   data-range="max"
                   class="ebay-range-input">
          </div>
        </div>
      `;
    }
  }).join('');
  
  // Attach change listeners
  ebayFiltersContainer.querySelectorAll('.ebay-filter-checkbox').forEach(checkbox => {
    checkbox.addEventListener('change', handleFilterChange);
  });
  
  ebayFiltersContainer.querySelectorAll('.ebay-range-input').forEach(input => {
    input.addEventListener('input', handleFilterChange);
  });

  // Collapsible behavior
    ebayFiltersContainer.querySelectorAll('.ebay-filter-title').forEach(title => {
    title.addEventListener('click', () => {
        const section = title.closest('.ebay-filter-section');
        section.classList.toggle('expanded');
    });
    });

}

function handleFilterChange(e) {
  const filterId = e.target.dataset.filter;
  
  if (e.target.type === 'checkbox') {
    if (!selectedFilters[filterId]) {
      selectedFilters[filterId] = [];
    }
    
    if (e.target.checked) {
      selectedFilters[filterId].push(e.target.dataset.value);
    } else {
      selectedFilters[filterId] = selectedFilters[filterId].filter(v => v !== e.target.dataset.value);
      if (selectedFilters[filterId].length === 0) {
        delete selectedFilters[filterId];
      }
    }
  } else if (e.target.classList.contains('ebay-range-input')) {
    const rangeType = e.target.dataset.range;
    if (!selectedFilters[filterId]) {
      selectedFilters[filterId] = {};
    }
    selectedFilters[filterId][rangeType] = e.target.value;
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
  const params = new URLSearchParams();

  // Fixed params
  params.set("_dcat", "9355");
  params.set("_fsrp", "1");
  params.set("rt", "nc");
  params.set("_from", "R40");
  
  // Search term
  params.set("_nkw", searchTerm);
  params.set("_sacat", "0");

  // Add filters - capitalize the first letter of each key
  Object.entries(filters).forEach(([key, value]) => {
    // Capitalize first letter: model -> Model, brand -> Brand
    const capitalizedKey = key.charAt(0).toUpperCase() + key.slice(1);
    
    if (Array.isArray(value)) {
      // Join multiple values with pipe
      params.set(capitalizedKey, value.join("|"));
    } else if (typeof value === 'object') {
      // Handle range filters
      if (value.min) params.set(`${capitalizedKey}_min`, value.min);
      if (value.max) params.set(`${capitalizedKey}_max`, value.max);
    } else {
      params.set(capitalizedKey, value);
    }
  });

  return `${baseUrl}?${params.toString()}`;
}

// Handle apply button
ebayApplyBtn.addEventListener('click', async () => {

    //  HARD GUARD
  if (isEbayScraping) return;

  setEbayScrapingState(true);


  const searchTerm = ebaySearchInput.value.trim();
  
  if (!searchTerm) {
    alert('Please enter a search term');
    return;
  }

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
    // TODO: THIS FUNCITON IS REALLY WEIRD BECAUSE IT BUILDS EVERYTHING EXCEPT THE TOP FILTERS
    const ebayUrl = buildEbayUrl(searchTerm, selectedFilters);
    console.log("eBay URL to scrape:", ebayUrl);

    const response = await sendExtensionMessage({
      action: "scrape",
      data: {
        directUrl: ebayUrl,
        competitors: ["eBay"],
        ebayFilterSold: ebayFilterSold,
        ebayFilterUsed: ebayFilterUKOnly,
        ebayFilterUKOnly: ebayFilterUsed,
      }
    });

    if (response.success) {
      console.log("Scraping success", response.results);
      renderResults(response.results);

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