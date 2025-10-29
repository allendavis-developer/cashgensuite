const addItemModal = document.getElementById('addItemModal');
const closeAddItemModal = document.getElementById('closeAddItemModal');
const saveItemBtn = document.getElementById('saveItemBtn');
const modalItemCategory = document.getElementById('modalItemCategory');
const modalItemSubcategory = document.getElementById('modalItemSubcategory');
const modalItemModel = document.getElementById('modalItemModel');
const attributesContainer = document.getElementById('attributes-container');

let currentAttributes = [];
const categoryTables = {};

populateCategories();

/* ---------- Category / Subcategory / Model ---------- */
function populateCategories() {
  modalItemCategory.innerHTML = '<option value="">Select category</option>';
  categories.forEach(c =>
    modalItemCategory.insertAdjacentHTML('beforeend', `<option value="${c.id}">${c.name}</option>`)
  );
}

function fetchSubcategorys(categoryId) {
  fetch(`/api/subcategorys/?category=${categoryId}`)
    .then(res => res.json())
    .then(data => {
      modalItemSubcategory.innerHTML = '<option value="">Select subcategory</option>';
      data.forEach(m => modalItemSubcategory.insertAdjacentHTML('beforeend', `<option value="${m.id}">${m.name}</option>`));
      // Clear model dropdown whenever subcategory list changes
      modalItemModel.innerHTML = '<option value="">Select model</option>';
    });
}

function fetchModels() {
  const categoryId = modalItemCategory.value;
  const subcategoryId = modalItemSubcategory.value;
  if (!categoryId || !subcategoryId) {
    modalItemModel.innerHTML = '<option value="">Select model</option>';
    return;
  }
  fetch(`/api/models/?category=${categoryId}&subcategory=${subcategoryId}`)
    .then(res => res.json())
    .then(data => {
      modalItemModel.innerHTML = '<option value="">Select model</option>';
      data.forEach(m => modalItemModel.insertAdjacentHTML('beforeend', `<option value="${m.id}">${m.name}</option>`));
    });
}

/* ---------- Attributes ---------- */
async function loadCategoryAttributes(categoryId) {
  const res = await fetch(`/api/category_attributes/?category=${categoryId}`);
  const data = await res.json();
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
    </div>`).join('');
}

/* ---------- Event Listeners ---------- */
modalItemCategory.addEventListener('change', () => {
  fetchModels();
  loadCategoryAttributes(modalItemCategory.value);
  fetchSubcategorys(modalItemCategory.value); // Pass category ID
});
modalItemSubcategory.addEventListener('change', fetchModels);
addItemBtn.addEventListener('click', () => { resetModal(); addItemModal.classList.add('active'); });
closeAddItemModal.addEventListener('click', () => addItemModal.classList.remove('active'));
saveItemBtn.addEventListener('click', addItemToTable);

/* ---------- UI Helpers ---------- */
function resetModal() {
  modalItemCategory.value = '';
  modalItemSubcategory.value = '';
  modalItemModel.innerHTML = '<option value="">Select model</option>';
  attributesContainer.innerHTML = '';
}
