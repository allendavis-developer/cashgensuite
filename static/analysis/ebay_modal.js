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

let selectedFilters = {};

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
    const response = await sendExtensionMessage({
      action: "scrape",
      data: {
        query: searchTerm,
        competitors: ["eBay"],
        category: "N/A",
        subcategory: "N/A",
        model: searchTerm,
        attributes: [],
        ebayFilterSold: false,
        ebayFilterUsed: false,
        ebayFilterUKOnly: false
      }
    });

    if (!response.success) {
      alert("Scraping failed: " + (response.error || "Unknown error"));
      return;
    }

    console.log(response.filters);

    // ✅ Use real filters from the scraper
    renderFilters(response.filters);

  } catch (error) {
    console.error('Error fetching filters:', error);
    ebayFiltersContainer.innerHTML =
      '<div style="text-align: center; padding: 20px; color: #c00;">Error loading filters. Please try again.</div>';
  }
});


function getMockFilters() {
  return [
    {
      name: 'Brand',
      id: 'brand',
      type: 'checkbox',
      options: [
        { value: 'apple', label: 'Apple', count: 1250 },
        { value: 'samsung', label: 'Samsung', count: 890 },
        { value: 'google', label: 'Google', count: 456 },
        { value: 'oneplus', label: 'OnePlus', count: 234 }
      ]
    },
    {
      name: 'Condition',
      id: 'condition',
      type: 'checkbox',
      options: [
        { value: 'new', label: 'New', count: 523 },
        { value: 'used', label: 'Used', count: 1876 },
        { value: 'refurbished', label: 'Manufacturer refurbished', count: 345 },
        { value: 'seller-refurbished', label: 'Seller refurbished', count: 234 }
      ]
    },
    {
      name: 'Price',
      id: 'price',
      type: 'range',
      min: 0,
      max: 1000
    },
    {
      name: 'Buying format',
      id: 'buying_format',
      type: 'checkbox',
      options: [
        { value: 'all', label: 'All listings', count: 2543 },
        { value: 'auction', label: 'Auction', count: 456 },
        { value: 'buy_it_now', label: 'Buy it now', count: 2087 }
      ]
    },
    {
      name: 'Item location',
      id: 'location',
      type: 'checkbox',
      options: [
        { value: 'uk', label: 'UK Only', count: 1876 },
        { value: 'europe', label: 'European Union', count: 456 },
        { value: 'worldwide', label: 'Worldwide', count: 211 }
      ]
    }
  ];
}

function renderFilters(filters) {
  selectedFilters = {};
  updateSelectedCount();
  
  ebayFiltersContainer.innerHTML = filters.map(filter => {
    if (filter.type === 'checkbox') {
      return `
        <div class="ebay-filter-section">
        <h4 class="ebay-filter-title">
            <span class="ebay-filter-arrow">▶</span>
            ${filter.name}
        </h4>          
        <div class="ebay-filter-options">
            ${filter.options.map(option => `
              <label class="ebay-filter-option">
                <input type="checkbox" 
                       data-filter="${filter.id}" 
                       data-value="${option.value}"
                       class="ebay-filter-checkbox">
                <span>${option.label}</span>
                ${option.count ? `<span class="ebay-filter-count">(${option.count})</span>` : ''}
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

// Handle apply button
ebayApplyBtn.addEventListener('click', async () => {
  const searchTerm = ebaySearchInput.value.trim();
  
  if (!searchTerm) {
    alert('Please enter a search term');
    return;
  }
  
  console.log('Applying eBay search with filters:', {
    searchTerm,
    filters: selectedFilters
  });
  
  // Show loading in results area
  ebayResultsContainer.style.display = 'block';
  ebayResultsContainer.innerHTML = '<div style="text-align: center; padding: 40px; color: #666;">Scraping eBay listings...</div>';
  
  try {
    // TODO: Replace with actual API call
    // const response = await fetch('/api/scrape-ebay/', {
    //   method: 'POST',
    //   headers: {
    //     'Content-Type': 'application/json',
    //     'X-CSRFToken': getCookie('csrftoken')
    //   },
    //   body: JSON.stringify({ 
    //     search_term: searchTerm,
    //     filters: selectedFilters
    //   })
    // });
    // const data = await response.json();
    
    // Mock data for now
    await new Promise(resolve => setTimeout(resolve, 1000));
    const mockResults = getMockResults();
    
    renderResults(mockResults);
  } catch (error) {
    console.error('Error scraping eBay:', error);
    ebayResultsContainer.innerHTML = '<div style="text-align: center; padding: 40px; color: #c00;">Error scraping eBay. Please try again.</div>';
  }
});

function getMockResults() {
  return {
    summary: {
      cex: '£450.00',
      cc_min: '£320.00',
      cc_avg: '£385.50',
      cc_mode: '£380.00',
      cc_median: '£390.00',
      cg_min: '£310.00',
      cg_avg: '£375.20',
      cg_mode: '£370.00',
      cg_median: '£380.00',
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

function renderResults(data) {
  ebayResultsContainer.innerHTML = `
    <div class="ebay-results-header">
      <h3>Market Summary</h3>
    </div>
    
    <table class="competitor-table" id="ebay-summary-table">
      <thead>
        <tr>
          <th>eBay Min</th>
          <th>eBay AVG</th>
          <th>eBay Mode</th>
          <th>eBay Median</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>${data.summary.ebay_min}</td>
          <td>${data.summary.ebay_avg}</td>
          <td>${data.summary.ebay_mode}</td>
          <td>${data.summary.ebay_median}</td>
        </tr>
      </tbody>
    </table>
    
    <div class="ebay-results-header" style="margin-top: 30px;">
      <h3>eBay Listings (${data.listings.length} results)</h3>
    </div>
    
    <div class="ebay-listings">
      ${data.listings.map(listing => `
        <div class="ebay-listing-card">
          <img src="${listing.image}" alt="${listing.title}" class="ebay-listing-image">
          <div class="ebay-listing-content">
            <a href="${listing.url}" target="_blank" class="ebay-listing-title">${listing.title}</a>
            <div class="ebay-listing-details">
              <span class="ebay-listing-price">${listing.price}</span>
              <span class="ebay-listing-condition">${listing.condition}</span>
            </div>
            <div class="ebay-listing-seller">Seller: ${listing.seller}</div>
          </div>
        </div>
      `).join('')}
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