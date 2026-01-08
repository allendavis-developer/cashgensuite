// ========== Elements ==========
const modalItemCategory = document.getElementById('modalItemCategory');
const modalItemSubcategory = document.getElementById('modalItemSubcategory');
const modalItemModel = document.getElementById('modalItemModel');
const addItemButton = document.querySelector('.add-item-button');
addItemButton.disabled = true; // safety

let currentAttributes = [];
let categoryTomSelect, subcategoryTomSelect, modelTomSelect;
let attributeTomSelects = {}; // Store TomSelect instances for attributes
let attributesResolved = false;


// ========== Local Cache ==========
const cache = {
  categories: [],
  subcategories: {}, // {categoryId: [subcatData]}
  models: {},        // {categoryId_subcatId: [modelData]}
  attributes: {}     // {categoryId: [attrs]}
};

let allowedCombinations = [];
let selectedVariants = {};

// ========== Initialize ==========
document.addEventListener('DOMContentLoaded', async () => {
  initTomSelects();
  await preloadData(); // Preload in background
  populateCategories();

});


// ========== Typeahead (Tom Select) ==========
function initTomSelects() {
  categoryTomSelect = new TomSelect('#modalItemCategory', { 
    placeholder: 'Select category...', 
    create: false 
  });
  
  subcategoryTomSelect = new TomSelect('#modalItemSubcategory', { 
    placeholder: 'Select subcategory...', 
    create: false 
  });
  
  modelTomSelect = new TomSelect('#modalItemModel', { 
    placeholder: 'Select model...',
    create: false,
    searchField: ['text', 'cex_stable_id'],
  });


  [categoryTomSelect, subcategoryTomSelect, modelTomSelect].forEach(ts => {
    ts.on('item_add', () => {
      ts.control_input.value = ts.control_input.value.trim();
    });
  });

  categoryTomSelect.on('change', (value) => {


    const categoryId = categoryTomSelect.getValue();
    if (!categoryId) return;

    currentAttributes = [];
    fetchSubcategories(categoryId);

    if (value) { 
      wizardState.source = 'cex';
      wizardState.cex.category = {
        id: value,
        name: categoryTomSelect.options[value]?.text || null
      };

      sendFieldUpdate('category', value);
    }
  });

  subcategoryTomSelect.on('change', (value) => {
    if (!value) return; 
    fetchModels();

    wizardState.cex.subcategory = {
      id: value,
      name: subcategoryTomSelect.options[value]?.text || null
    };

    sendFieldUpdate('subcategory', value);
  });

  modelTomSelect.on('change', value => {
    addItemButton.disabled = true; // 🔒 lock immediately
    attributesResolved = false;

    clearDynamicAttributes();
    Object.values(attributeTomSelects).forEach(ts => ts.destroy());
    attributeTomSelects = {};

    allowedCombinations = [];
    selectedVariants = {};
    currentAttributes = [];
    wizardState.cex.attributes = {};
    wizardState.cex.prices = null;


    if (value)  { 
      const opt = modelTomSelect.options[value];
      wizardState.cex.model = {
        id: value,
        name: opt?.text || null,
        cexStableId: opt?.cex_stable_id || null
      };

      sendFieldUpdate('model', value);
    } 
  });

}

addItemButton.addEventListener('click', async () => {
  if (addItemButton.disabled) return;

  addItemButton.classList.add('loading');
  addItemButton.disabled = true;

  try {
    const categoryId = categoryTomSelect.getValue();
    const subcategoryId = subcategoryTomSelect.getValue();
    const modelId = modelTomSelect.getValue();

    const modelOption = modelTomSelect.options[modelId];

    const payload = {
      categoryId,
      subcategoryId,
      modelId,
      cexStableId: modelOption?.cex_stable_id || null,
      attributes: selectedVariants,
    };

    const priceData = await fetchPriceDataCEX(payload);
    renderCexResults(priceData);

    wizardState.cex.prices = {
      cexSellingPrice: priceData.cex_selling_price,
      buying: {
        start: priceData.buying_start_price,
        mid: priceData.buying_mid_price,
        end: priceData.buying_end_price
      },
      rrp: priceData.selling_price,
      rrp_pct: priceData.cex_rrp_pct,
      lastUpdated: priceData.cex_last_price_updated_date
    };


  } catch (err) {
    console.error('Failed to fetch price data:', err);
  } finally {
    addItemButton.classList.remove('loading');
    updateAddItemButtonState(); // restore enabled state correctly
  }
});

function updateSuggestedRrpMethod(rrp, baseCexPrice) {
  if (!rrp || !baseCexPrice) return;
  
  const pct = Math.round((rrp / baseCexPrice) * 100);
  wizardState.cex.suggestedRrpMethod = `Percentage of CEX Price (${pct}%)`;
}


function setMargin(el, rrp, offer) {
  if (!rrp || !offer) {
    el.textContent = '—';
    el.className = 'margin-inline';
    return;
  }

  const pct = Math.round(((rrp - offer) / rrp) * 100);

  el.textContent = `${pct}%`;

  el.className = 'margin-inline ' +
    (pct >= 40 ? 'good' : pct >= 25 ? 'warn' : 'bad');
}

function recalcFromRrp(rrp) {
  const data = window.currentPriceData;
  if (!data || !rrp) return;

  // Keep CeX % in sync (without triggering pct input event)
  const pct = (data.base_cex_price / rrp) * 100;
  const rrpPctInput = document.getElementById('rrpPct');
  
  // Remove listener temporarily to avoid feedback loop
  const oldHandler = rrpPctInput.oninput;
  rrpPctInput.oninput = null;
  rrpPctInput.value = Math.round(pct);
  setTimeout(() => { rrpPctInput.oninput = oldHandler; }, 0);

  // Recalculate offers
  const offers = {
    start: data.buying_start_price,
    mid: data.buying_mid_price,
    end: data.buying_end_price,
  };

  setMargin(document.getElementById('marginStart'), rrp, offers.start);
  setMargin(document.getElementById('marginMid'), rrp, offers.mid);
  setMargin(document.getElementById('marginEnd'), rrp, offers.end);

  // Update final margin
  updateActiveOffer({
    ...data,
    selling_price: rrp
  });
  updateSuggestedRrpMethod(rrp, data.base_cex_price);

}  


function recalcFromPct(pct) {
  const data = window.currentPriceData;
  if (!data || !pct) return;

  const rrp = Math.round((data.base_cex_price * pct) / 100);
  const rrpInput = document.getElementById('suggestedRrp');
  
  // Remove listener temporarily to avoid feedback loop
  const oldHandler = rrpInput.oninput;
  rrpInput.oninput = null;
  rrpInput.value = rrp;
  setTimeout(() => { rrpInput.oninput = oldHandler; }, 0);

  // Recalculate margins
  const offers = {
    start: data.buying_start_price,
    mid: data.buying_mid_price,
    end: data.buying_end_price,
  };

  setMargin(document.getElementById('marginStart'), rrp, offers.start);
  setMargin(document.getElementById('marginMid'), rrp, offers.mid);
  setMargin(document.getElementById('marginEnd'), rrp, offers.end);

  // Update final margin
  updateActiveOffer({
    ...data,
    selling_price: rrp
  });

  updateSuggestedRrpMethod(rrp, data.base_cex_price);
}


document.getElementById('suggestedRrp').addEventListener('input', e => {
  const rrp = Number(e.target.value);
  recalcFromRrp(rrp);
});

document.getElementById('rrpPct').addEventListener('input', e => {
  const pct = Number(e.target.value);
  recalcFromPct(pct);
});



function renderCexResults(data) {
  const panel = document.getElementById('cexResults');
  panel.hidden = false;

  const money = v => v != null ? `£${v}` : '—';

  document.getElementById('cexPrice').textContent =
    money(data.cex_selling_price);

  document.getElementById('cexUpdated').textContent =
    data.cex_last_price_updated_date || '—';

  const rrp = data.selling_price;

  // Set input values (not textContent)
  document.getElementById('suggestedRrp').value = rrp || '';
  document.getElementById('rrpPct').value =
    data.cex_rrp_pct != null ? Math.round(data.cex_rrp_pct * 100) : '';

  document.getElementById('offerStart').textContent = `£${data.buying_start_price}`;
  document.getElementById('offerMid').textContent = `£${data.buying_mid_price}`;
  document.getElementById('offerEnd').textContent = `£${data.buying_end_price}`;

  setMargin(
    document.getElementById('marginStart'),
    rrp,
    data.buying_start_price
  );

  setMargin(
    document.getElementById('marginMid'),
    rrp,
    data.buying_mid_price
  );

  setMargin(
    document.getElementById('marginEnd'),
    rrp,
    data.buying_end_price
  );

  window.currentPriceData = {
    ...data,
    base_cex_price: data.cex_selling_price
  };
  
  activeOfferIndex = 0;
  updateActiveOffer({
    ...data,
    selling_price: document.getElementById('suggestedRrp').value || data.selling_price
  });


  // Add this line to always populate suggestedRrpMethod
  const baseCex = data.cex_selling_price || 0;
  const pct = baseCex ? Math.round((rrp / baseCex) * 100) : 0;
  wizardState.cex.suggestedRrpMethod = `Percentage of CEX Price (${pct}%)`;
}


const offerOrder = ['start', 'mid', 'match_cex'];
let activeOfferIndex = 0;

const offerRisk = {
  start: 'safe',
  mid: 'mid',
  match_cex: 'risky'
};

function getOfferValue(type, data) {
  return {
    start: data.buying_start_price,
    mid: data.buying_mid_price,
    match_cex: data.buying_end_price,
  }[type];
}

function updateActiveOffer(data) {
  const offers = document.querySelectorAll('.pricing-item.offer');
  offers.forEach(el =>
    el.classList.remove('active', 'safe', 'mid', 'risky')
  );

  const type = offerOrder[activeOfferIndex];
  const el = document.querySelector(
    `.pricing-item.offer[data-offer="${type}"]`
  );
  if (!el) return;

  const rrp = data.selling_price;
  const offer = getOfferValue(type, data);
  const pct = Math.round(((rrp - offer) / rrp) * 100);

  // 🔒 Forced risk by offer position
  el.classList.add('active', offerRisk[type]);

  // Update final margin display
  document.getElementById('margin').textContent = `${pct}%`;

  // =====================
  //  Persist selection
  // =====================
  wizardState.cex.selectedOffer = {
    type,               // 'start' | 'mid' | 'match_cex'
    price: offer,       // numeric £ value
    marginPct: pct,     // numeric %
    risk: offerRisk[type]
  };
}


document.addEventListener('keydown', e => {
  if (e.key !== 'Tab') return;

  const panelVisible = !document.getElementById('cexResults').hidden;
  if (!panelVisible) return;

  e.preventDefault(); // keep focus in pricing

  activeOfferIndex = (activeOfferIndex + 1) % offerOrder.length;
  updateActiveOffer(window.currentPriceData);
});


document.querySelectorAll('.pricing-item.offer').forEach(el => {
  el.addEventListener('click', () => {
    activeOfferIndex = offerOrder.indexOf(el.dataset.offer);
    updateActiveOffer(window.currentPriceData);
  });
});

// ========== Preload all categories ==========
async function preloadData() {
  try {
    const res = await fetch('/api/categories/');
    const data = await res.json();
    cache.categories = data.categories;
    console.log("Preloaded categories", cache.categories);
  } catch (err) {
    console.error('Failed to preload categories', err);
  }
}

// ========== Populate Category Dropdown ==========
function populateCategories() {
  categoryTomSelect.clear();
  categoryTomSelect.clearOptions();

  cache.categories.forEach(c => {
    categoryTomSelect.addOption({ value: c.id, text: c.name });
  });
  
  categoryTomSelect.refreshOptions(false);
}

// ========== Fetch & Cache Subcategories ==========
async function fetchSubcategories(categoryId) {
  if (!categoryId) return;
  if (cache.subcategories[categoryId]) {
    renderSubcategories(cache.subcategories[categoryId]);
    return;
  }

  const res = await fetch(`/api/subcategorys/?category=${categoryId}`);
  const data = await res.json();
  cache.subcategories[categoryId] = data;
  renderSubcategories(data);
}

function renderSubcategories(data) {
  subcategoryTomSelect.clear();
  subcategoryTomSelect.clearOptions();

  const sorted = [...data].sort((a, b) => 
    a.name.localeCompare(b.name)
  );

  sorted.forEach(sc => {
    subcategoryTomSelect.addOption({ value: sc.id, text: sc.name });
  });

  subcategoryTomSelect.refreshOptions(false);

  modelTomSelect.clear();
  modelTomSelect.clearOptions();
}

async function fetchPriceDataCEX({ 
  categoryId, 
  subcategoryId, 
  modelId, 
  cexStableId, 
  attributes 
}) {
  const response = await fetch('/api/get-selling-and-buying-price/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken'),
    },
    body: JSON.stringify({
      categoryId,
      subcategoryId,
      modelId,
      cex_stable_id: cexStableId,
      attributes,
    }),
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const result = await response.json();

  if (!result.success) {
    throw new Error(result.error || 'Failed to get price data');
  }

  return result;
}


// ========== Fetch & Cache Models ==========
async function fetchModels() {
  const categoryId = categoryTomSelect.getValue();
  const subcategoryId = subcategoryTomSelect.getValue();
  if (!categoryId || !subcategoryId) return;

  const key = `${categoryId}_${subcategoryId}`;
  if (cache.models[key]) {
    renderModels(cache.models[key]);
    return;
  }

  const res = await fetch(`/api/models/?category=${categoryId}&subcategory=${subcategoryId}`);
  const data = await res.json();
  cache.models[key] = data;
  renderModels(data);
}

function renderModels(data) {
  modelTomSelect.clear();
  modelTomSelect.clearOptions();
  
  const sorted = [...data].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' })
  );

  sorted.forEach(m => {
    modelTomSelect.addOption({
      value: m.id,
      text: m.name,
      cex_stable_id: m.cex_stable_id || '',
      _raw: m, 
    });
  });

  modelTomSelect.refreshOptions(false);
}

async function sendFieldUpdate(fieldName, value) {
  try {
    const res = await fetch('/api/save_input/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: JSON.stringify({ field: fieldName, value }),
    });

    const data = await res.json();
    console.log('Backend response:', data);

    // Handle model selection and variants
    if (fieldName === 'model' && data.variants) {

      const hasAttributes = Object.keys(data.variants).length > 0;

      if (!hasAttributes) {
        attributesResolved = true;
        updateAddItemButtonState();
        return;
      }

      console.log('Received variants from backend:', data.variants);
      console.log('Received combinations from backend:', data.combinations);

      allowedCombinations = data.combinations || [];
      selectedVariants = {};

      const attrs = Object.entries(data.variants).map(([name, options]) => ({
          id: `model_${name}`,
          name,
          label: name.charAt(0).toUpperCase() + name.slice(1),
          field_type: 'select',
          options
        }));

        currentAttributes = attrs;
        renderAttributes(attrs);

    } else {
      // Track variant selections
      const attrMatch = currentAttributes.find(a => a.name === fieldName || a.label === fieldName || `attr_${a.id}` === fieldName);
      if (attrMatch) {
        selectedVariants[attrMatch.name] = value;
        wizardState.cex.attributes = {
          ...selectedVariants
        };

        filterRemainingAttributes();
        updateAddItemButtonState();

      }
    }
  } catch (err) {
    console.error(`Failed to send ${fieldName}:`, err);
  }
}

function updateAddItemButtonState() {
  if (!attributesResolved) {
    addItemButton.disabled = true;
    return;
  }

  const modelSelected = !!modelTomSelect.getValue();

  if (modelSelected && currentAttributes.length === 0) {
    addItemButton.disabled = false;
    return;
  }

  const allAttrsSelected =
    currentAttributes.length > 0 &&
    currentAttributes.every(attr => selectedVariants[attr.name]);

  addItemButton.disabled = !(modelSelected && allAttrsSelected);
}


function clearDynamicAttributes() {
  document
    .querySelectorAll('.search-field[data-dynamic="true"], .divider[data-dynamic="true"]')
    .forEach(el => el.remove());
}


function filterRemainingAttributes() {
  if (allowedCombinations.length === 0) return;

  // Filter combinations based on current selections
  const validCombos = allowedCombinations.filter(combo =>
    Object.keys(selectedVariants).every(
      key => combo[key] === selectedVariants[key]
    )
  );

  currentAttributes.forEach(attr => {
    const ts = attributeTomSelects[attr.id];
    if (!ts) return;

    const allowedOptions = [...new Set(validCombos.map(c => c[attr.name]))]
      .sort((a, b) => {
        const numA = parseFloat(a);
        const numB = parseFloat(b);
        const isNumA = !isNaN(numA) && a.trim() !== "";
        const isNumB = !isNaN(numB) && b.trim() !== "";

        if (isNumA && isNumB) return numA - numB;
        if (isNumA) return -1;
        if (isNumB) return 1;
        return a.localeCompare(b);
      });

    const currentValue = ts.getValue();

    // 🔴 CRITICAL PART: clear invalid selection
    if (currentValue && !allowedOptions.includes(currentValue)) {
      ts.clear();
      delete selectedVariants[attr.name];
    }

    ts.clearOptions();
    allowedOptions.forEach(opt =>
      ts.addOption({ value: opt, text: opt })
    );

    ts.refreshOptions(false);
      
    if (!ts.getValue() && allowedOptions.length === 1) {
      ts.setValue(allowedOptions[0]);
      selectedVariants[attr.name] = allowedOptions[0];

      requestAnimationFrame(() => {
        updateAddItemButtonState();
      });
    }
    
  });
}


function renderAttributes(attrs) {
    const row = document.getElementById('searchBarRow');
  clearDynamicAttributes();

  attrs.forEach(attr => {
    // Divider
    const divider = document.createElement('div');
    divider.className = 'divider';
    divider.dataset.dynamic = 'true';

    // Field
    const field = document.createElement('div');
    field.className = 'search-field';
    field.dataset.dynamic = 'true';
    field.innerHTML = `
      <label>${attr.label || attr.name}</label>
      <select id="attr_${attr.id}"></select>
    `;

    row.appendChild(divider);
    row.appendChild(field);

    const ts = new TomSelect(`#attr_${attr.id}`, {
      placeholder: `${attr.label || attr.name}...`,
      create: false,
      options: (attr.options || []).map(o => ({ value: o, text: o }))
    });

    attributeTomSelects[attr.id] = ts;

    ts.on('change', value => {
      if (value) sendFieldUpdate(attr.name, value);
    });

    // Auto-select if only one option
    if (attr.options?.length === 1) {
      ts.setValue(attr.options[0]);
      sendFieldUpdate(attr.name, attr.options[0]);

      requestAnimationFrame(() => {
        updateAddItemButtonState();
      });
    }
  });

  attributesResolved = true;


  requestAnimationFrame(() => {
    updateAddItemButtonState();
  });

}

document.addEventListener('DOMContentLoaded', () => {
  const confirmBtn = document.querySelector('.cex-confirm-button');

  confirmBtn?.addEventListener('click', () => {
    window.ResearchWizard.showOverview();
  });
});

// Handle the CeX back button
document.querySelector('.rw-back-cex')?.addEventListener('click', () => {
  window.ResearchWizard.showOverview();
});


// ========== Utility Functions ==========
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === (name + '=')) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}