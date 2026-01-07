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

  categoryTomSelect.on('change', () => {
    const categoryId = categoryTomSelect.getValue();
    if (!categoryId) return; // prevents empty requests

    currentAttributes = []; // clear old ones
    fetchSubcategories(categoryId);

  });

  subcategoryTomSelect.on('change', fetchModels);
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
    if (value) sendFieldUpdate('category', value);
  });

  subcategoryTomSelect.on('change', (value) => {
    if (value) sendFieldUpdate('subcategory', value);
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

    if (value) sendFieldUpdate('model', value);
  });



}



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
      cex_stable_id: m.cex_stable_id || ''
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