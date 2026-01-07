// ========== Modal Elements ==========
const addItemModal = document.getElementById('addItemModal');
const closeAddItemModal = document.getElementById('closeAddItemModal');
const saveItemBtn = document.getElementById('saveItemBtn');
const modalItemCategory = document.getElementById('modalItemCategory');
const modalItemSubcategory = document.getElementById('modalItemSubcategory');
const modalItemModel = document.getElementById('modalItemModel');
const attributesContainer = document.getElementById('attributes-container');
const categoryTables = {};
let currentAttributes = [];
let categoryTomSelect, subcategoryTomSelect, modelTomSelect;
let attributeTomSelects = {}; // Store TomSelect instances for attributes

// ========== Local Cache ==========
const cache = {
  categories: [],
  subcategories: {}, // {categoryId: [subcatData]}
  models: {},        // {categoryId_subcatId: [modelData]}
  attributes: {}     // {categoryId: [attrs]}
};




// ========== Initialize ==========
document.addEventListener('DOMContentLoaded', async () => {
  initTomSelects();
  await preloadData(); // Preload in background
  populateCategories();

  categoryTomSelect.on('change', () => {

    const categoryId = categoryTomSelect.getValue();
    if (!categoryId) return; // <-- prevents empty requests

    currentAttributes = []; // clear old ones
    attributesContainer.innerHTML = '';
    fetchSubcategories(categoryTomSelect.getValue());

        
    // Always display Condition attribute immediately
    const defaultConditionAttr = {
      id: 'default_condition',
      name: 'condition',
      label: 'Condition',
      field_type: 'select',
      options: ['New', 'Used', 'Refurbished'] // or whatever your default options are
    };
    
    currentAttributes = [defaultConditionAttr];
    renderAttributes([defaultConditionAttr]);
    loadCategoryAttributes(categoryTomSelect.getValue());


  });

  subcategoryTomSelect.on('change', fetchModels);

});

async function loadCategoryAttributes(categoryId) {
  let data;
  if (cache.attributes[categoryId]) {
    data = cache.attributes[categoryId];
  } else {
    const res = await fetch(`/api/category_attributes/?category=${categoryId}`);
    data = await res.json();
    cache.attributes[categoryId] = data;
  }
  
  currentAttributes = data;
  // renderAttributes(data);
}

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
    searchField: ['text', 'cex_stable_id'], // 👈 searchable but hidden
  });


  [categoryTomSelect, subcategoryTomSelect, modelTomSelect].forEach(ts => {
  ts.on('item_add', () => {
    ts.control_input.value = ts.control_input.value.trim();
  });
});


  // Attach the "Add new model" behavior ONCE
  modelTomSelect.on('change', async (value) => {
    if (value === '__new__') {
      const categoryId = categoryTomSelect.getValue();
      const subcategoryId = subcategoryTomSelect.getValue();
      if (categoryId && subcategoryId) {
        await handleAddNewModel(categoryId, subcategoryId);
      }
    }
  });

  categoryTomSelect.on('change', (value) => {
    if (value) sendFieldUpdate('category', value);
  });

  subcategoryTomSelect.on('change', (value) => {
    if (value) sendFieldUpdate('subcategory', value);
  });

  modelTomSelect.on('change', (value) => {
    if (value && value !== '__new__') sendFieldUpdate('model', value);
  });
}

let isInitializing = false;



function validateModalInputs() {
  const category = categoryTomSelect.getValue();
  const subcategory = subcategoryTomSelect.getValue();
  const model = modelTomSelect.getValue();
  let isValid = true;
  let errorMessages = [];

  if (!category) {
    isValid = false;
    errorMessages.push('Please select a category.');
  }
  if (!subcategory) {
    isValid = false;
    errorMessages.push('Please select a subcategory.');
  }
  if (!model) {
    isValid = false;
    errorMessages.push('Please select a model.');
  }

  // Validate dynamic attributes
  for (const attr of currentAttributes) {
    const attrTs = attributeTomSelects[attr.id];
    let value;
    
    if (attrTs) {
      value = attrTs.getValue();
    } else {
      const input = document.getElementById(`attr_${attr.id}`);
      value = input ? input.value.trim() : '';
    }
    
    if (!value) {
      isValid = false;
      errorMessages.push(`Please fill the attribute: ${attr.label || attr.name}`);
      
      if (attrTs) {
        attrTs.wrapper.classList.add('input-error');
      } else {
        const input = document.getElementById(`attr_${attr.id}`);
        input?.classList.add('input-error');
      }
    } else {
      if (attrTs) {
        attrTs.wrapper.classList.remove('input-error');
      } else {
        const input = document.getElementById(`attr_${attr.id}`);
        input?.classList.remove('input-error');
      }
    }
  }

  if (!isValid) {
    alert(errorMessages.join('\n'));
  }

  return isValid;
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

  modelTomSelect.addOption({ value: '__new__', text: 'Add new model...' });
  modelTomSelect.refreshOptions(false);
}


async function handleAddNewModel(categoryId, subcategoryId) {
  const newModelName = prompt('Enter the new model name:');
  if (!newModelName) {
    modelTomSelect.clear(); // reset selection if cancelled
    return;
  }

  try {
    const res = await fetch('/api/add_model/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'), 
      },
      body: JSON.stringify({
        name: newModelName,
        category: categoryId,
        subcategory: subcategoryId,
      }),
    });

    const data = await res.json();

    if (res.ok) {
      // Cache + select it
      const key = `${categoryId}_${subcategoryId}`;
      if (!cache.models[key]) cache.models[key] = [];
      cache.models[key].push(data);

      modelTomSelect.addOption({ value: data.id, text: data.name });
      modelTomSelect.refreshOptions(false);
      modelTomSelect.setValue(data.id);

      alert(`Model "${data.name}" added successfully!`);
    } else {
      alert(data.error || 'Error adding model.');
      modelTomSelect.clear();
    }
  } catch (err) {
    console.error(err);
    alert('Failed to add model.');
    modelTomSelect.clear();
  }
}
let allowedCombinations = [];
let selectedVariants = {};
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
      console.log('Received variants from backend:', data.variants);
      console.log('Received combinations from backend:', data.combinations);

      allowedCombinations = data.combinations || [];
      selectedVariants = {};

      // Build attribute objects like the old category attributes
      const attrs = Object.keys(data.variants).map((attrName, idx) => ({
        id: `model_${attrName}`,       // pseudo-ID
        name: attrName,
        label: attrName.charAt(0).toUpperCase() + attrName.slice(1),
        field_type: 'select',
        options: data.variants[attrName],
      }));

      // Update currentAttributes and render
      currentAttributes = attrs;
      renderAttributes(attrs);
    } else {
      // Track variant selections
      const attrMatch = currentAttributes.find(a => a.name === fieldName || a.label === fieldName || `attr_${a.id}` === fieldName);
      if (attrMatch) {
        selectedVariants[attrMatch.name] = value;
        filterRemainingAttributes();
      }
    }
  } catch (err) {
    console.error(`Failed to send ${fieldName}:`, err);
  }
}



function filterRemainingAttributes() {
  if (allowedCombinations.length === 0) return;

  // Filter combinations based on current selections
  const validCombos = allowedCombinations.filter(combo => {
    return Object.keys(selectedVariants).every(key => combo[key] === selectedVariants[key]);
  });

  // Update options for unselected attributes
  currentAttributes.forEach(attr => {
    if (!selectedVariants[attr.name]) {
      const ts = attributeTomSelects[attr.id];
      if (ts) {
        console.log("sorting alphabetically");
        const allowedOptions = [...new Set(validCombos.map(c => c[attr.name]))]
          .sort((a, b) => {
            const numA = parseFloat(a);
            const numB = parseFloat(b);
            const isNumA = !isNaN(numA) && a.trim() !== "";
            const isNumB = !isNaN(numB) && b.trim() !== "";

            if (isNumA && isNumB) {
              return numA - numB;          // numeric sort
            } else if (isNumA) {
              return -1;                   // numbers first
            } else if (isNumB) {
              return 1;
            }

            return a.localeCompare(b);    // alphabetical fallback
          });

        ts.clearOptions();
        allowedOptions.forEach(opt => {
          ts.addOption({ value: opt, text: opt });
        });
        ts.refreshOptions(false);
      }
    }
  });
}


function renderAttributes(attrs) {
  // Destroy existing TomSelect instances
  Object.values(attributeTomSelects).forEach(ts => {
    if (ts && ts.destroy) {
      ts.destroy();
    }
  });
  attributeTomSelects = {};

  attributesContainer.innerHTML = attrs.map((attr, index) => `
    <div class="input-group">
      <label>${attr.label || attr.name}</label>
      ${attr.field_type === 'select'
        ? `<select id="attr_${attr.id}" class="input-field"></select>`
        : `<input type="${attr.field_type === 'number' ? 'number' : 'text'}" id="attr_${attr.id}" class="input-field">`}
    </div>
  `).join('');

  // Initialize TomSelect for select attributes
  attrs.forEach((attr, index) => {
    if (attr.field_type === 'select') {
      const selectElement = document.getElementById(`attr_${attr.id}`);
      if (selectElement) {
        const ts = new TomSelect(`#attr_${attr.id}`, {
        placeholder: `Select ${attr.label || attr.name}...`,
        create: false,
        options: (attr.options || [])
          .slice()
          .sort((a, b) => {
            // Natural sort: extract numbers and compare intelligently
            const numA = parseFloat(a.match(/\d+(\.\d+)?/)?.[0]);
            const numB = parseFloat(b.match(/\d+(\.\d+)?/)?.[0]);
            
            if (!isNaN(numA) && !isNaN(numB) && numA !== numB) {
              return numA - numB;
            }
            return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
          })
          .map(opt => ({ value: opt, text: opt })),
      });



      attributeTomSelects[attr.id] = ts;

      // 🔹 Auto-select if only one option
      if (attr.options && attr.options.length === 1) {
        const onlyOption = attr.options[0];
        ts.setValue(onlyOption);
        sendFieldUpdate(attr.name || attr.label || `attr_${attr.id}`, onlyOption);
      }

      ts.on('change', (value) => {
        if (value) sendFieldUpdate(attr.name || attr.label || `attr_${attr.id}`, value);
      });
      }
    }
  });

}


// ========== UI & Event Handlers ==========
function resetModal() {
  categoryTomSelect.clear();
  subcategoryTomSelect.clear();
  subcategoryTomSelect.clearOptions();
  modelTomSelect.clear();
  modelTomSelect.clearOptions();
  attributesContainer.innerHTML = '';
  currentAttributes = [];
  
  // Destroy attribute TomSelects
  Object.values(attributeTomSelects).forEach(ts => {
    if (ts && ts.destroy) {
      ts.destroy();
    }
  });
  attributeTomSelects = {};
}

addItemBtn.addEventListener('click', async () => {
  resetModal();
  addItemModal.classList.add('active');
  populateCategories();

  if (lastSelections.category) {
      // Set initialization flag
      isInitializing = true;

    categoryTomSelect.setValue(lastSelections.category);
    await fetchSubcategories(lastSelections.category);

    if (lastSelections.subcategory) {
        subcategoryTomSelect.setValue(String(lastSelections.subcategory), true);
        await fetchModels();
    }
  }


});


closeAddItemModal.addEventListener('click', () => addItemModal.classList.remove('active'));


saveItemBtn.addEventListener('click', () => {
  if (!validateModalInputs()) {
    // stop here, do not close modal or table
    return;
  }

  // All inputs are valid, proceed to add the item
  addItemToTable();
});

// Handle Enter on Save button
saveItemBtn.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    saveItemBtn.click();
  }
});