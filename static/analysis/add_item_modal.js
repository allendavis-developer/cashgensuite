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
    currentAttributes = []; // clear old ones
    attributesContainer.innerHTML = '';
    fetchSubcategories(categoryTomSelect.getValue());
    loadCategoryAttributes(categoryTomSelect.getValue());
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
    create: false 
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
  
  data.forEach(sc => {
    subcategoryTomSelect.addOption({ value: sc.id, text: sc.name });
  });
  
  subcategoryTomSelect.refreshOptions(false);
  
  // Clear models
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

  // Attach “Add new model” behavior
  modelTomSelect.on('change', async (value) => {
    if (value === '__new__') {
      await handleAddNewModel(categoryId, subcategoryId);
    }
  });

}

function renderModels(data) {
  modelTomSelect.clear();
  modelTomSelect.clearOptions();
  
  data.forEach(m => {
    modelTomSelect.addOption({ value: m.id, text: m.name });
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


// ========== Attributes ==========
async function loadCategoryAttributes(categoryId) {
  if (cache.attributes[categoryId]) {
    renderAttributes(cache.attributes[categoryId]);
    return;
  }

  const res = await fetch(`/api/category_attributes/?category=${categoryId}`);
  const data = await res.json();
  cache.attributes[categoryId] = data;
  currentAttributes = data; 

  renderAttributes(data);
}

function renderAttributes(attrs) {
  attributesContainer.innerHTML = attrs.map(attr => `
    <div class="input-group">
      <label>${attr.label || attr.name}</label>
      ${attr.field_type === 'select'
        ? `<select id="attr_${attr.id}" class="input-field">
            <option value="">-- Select ${attr.label || attr.name} --</option>
            ${(attr.options || []).map(o => `<option value="${o}">${o}</option>`).join('')}
          </select>`
        : `<input type="${attr.field_type === 'number' ? 'number' : 'text'}" id="attr_${attr.id}" class="input-field">`}
    </div>
  `).join('');
}

// ========== UI & Event Handlers ==========
function resetModal() {
  categoryTomSelect.clear();
  subcategoryTomSelect.clear();
  subcategoryTomSelect.clearOptions();
  modelTomSelect.clear();
  modelTomSelect.clearOptions();
  attributesContainer.innerHTML = '';
}

addItemBtn.addEventListener('click', () => {
  resetModal();
  addItemModal.classList.add('active');
  populateCategories();
});


closeAddItemModal.addEventListener('click', () => addItemModal.classList.remove('active'));


saveItemBtn.addEventListener('click', addItemToTable);