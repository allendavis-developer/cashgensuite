function setSelectValueWithTomSelect(selectElement, value) {
    if (!selectElement) return;
    if (selectElement.tomselect) {
        selectElement.tomselect.setValue(value, false);
        selectElement.dispatchEvent(new Event('change'));
    } else {
        selectElement.value = value;
        selectElement.dispatchEvent(new Event('change'));
    }
}

function setPrimaryOrNativeSelectValue(selectId, value) {
    if (typeof setPrimarySelectValue === 'function') {
        console.log("setPrimaryOrNativeSelectValue");
        setPrimarySelectValue(selectId, value);
        return;
    }
    const select = document.getElementById(selectId);
    if (select) {
        setSelectValueWithTomSelect(select, value);
    }
}

async function prefillFormFromURL() {
    const urlParams = new URLSearchParams(window.location.search);

    const categoryId = urlParams.get('categoryId');
    const subcategoryId = urlParams.get('subcategoryId');
    const modelId = urlParams.get('modelId');
    const attributesParam = urlParams.get('attributes');

    if (!categoryId || !subcategoryId || !modelId) {
        console.log('No prefill data found in URL');
        return;
    }

    console.log('Prefilling form with:', { categoryId, subcategoryId, modelId, attributesParam });

    try {
        // Parse attributes from URL-encoded JSON
        let attributes = {};
        if (attributesParam) {
            try {
                attributes = JSON.parse(decodeURIComponent(attributesParam));
            } catch (e) {
                console.error('Failed to parse attributes:', e);
            }
        }

        // 1. Select category
        const categorySelect = document.getElementById('category');
        if (categorySelect) {
            setPrimaryOrNativeSelectValue('category', categoryId);

            // Wait for subcategories to load
            await waitForElement('#subcategory option[value]:not([value=""])');

            // 2. Select subcategory
                const subcategorySelect = document.getElementById('subcategory');
                if (subcategorySelect) {
                    setPrimaryOrNativeSelectValue('subcategory', subcategoryId);
                    
                await loadModelsAndPopulate();
                // Wait for models to load
                await waitForElement('#model option[value]:not([value=""])');

                // 3. Select model
                const modelSelect = document.getElementById('model');
                if (modelSelect) {
                    console.log("setting model!", modelId);
                    setPrimaryOrNativeSelectValue('model', modelId);
                }

                await loadListings();
            }
        }

        console.log('Form prefilled successfully');
        setSearchTerm();
        maybeCheckExistingItems();


    } catch (error) {
        console.error('Error prefilling form:', error);
    }
}

/**
 * Helper function to wait for an element to appear in the DOM
 */
function waitForElement(selector, timeout = 5000) {
    return new Promise((resolve, reject) => {
        const element = document.querySelector(selector);
        if (element) {
            resolve(element);
            return;
        }

        const observer = new MutationObserver(() => {
            const element = document.querySelector(selector);
            if (element) {
                observer.disconnect();
                clearTimeout(timer);
                resolve(element);
            }
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        const timer = setTimeout(() => {
            observer.disconnect();
            reject(new Error(`Timeout waiting for ${selector}`));
        }, timeout);
    });
}

// Call prefillFormFromURL after DOM is loaded
document.addEventListener('DOMContentLoaded', function () {
    const costInput = document.getElementById('cost-price');
    if (costInput && costInput.value) {
        setRRPAfterTable(costInput.value);
    }

    prefillFormFromURL();
});
