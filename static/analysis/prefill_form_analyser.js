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

                // Wait for models to load
                await waitForElement('#model option[value]:not([value=""])');

                // 3. Select model
                    const modelSelect = document.getElementById('model');
                    if (modelSelect) {
                        setPrimaryOrNativeSelectValue('model', modelId);

                    if (attributes && Object.keys(attributes).length > 0) {
                        // Wait for at least one attribute field to appear
                        await waitForElement('[id^="attr_"]', 5000); // waits up to 5s for any attribute field

                        // 4. Fill in attributes
                        if (Array.isArray(attributes)) {
                            // Array-style attributes: [{id, value}, ...]
                            attributes.forEach(attr => {
                                const attrSelect = document.getElementById(`attr_${attr.id}`);
                                if (attrSelect) {
                                    setSelectValueWithTomSelect(attrSelect, attr.value);
                                    console.log(`Set attribute ${attr.id} to ${attr.value}`);
                                } else {
                                    console.warn(`Attribute field attr_${attr.id} not found`);
                                }
                            });
                        } else {
                            // Object-style attributes: {key: value, ...}
                            for (const [key, value] of Object.entries(attributes)) {
                                const attrSelect = document.getElementById(`attr_${key}`);
                                if (attrSelect) {
                                    setSelectValueWithTomSelect(attrSelect, value);
                                    console.log(`Set attribute ${key} to ${value}`);
                                } else {
                                    console.warn(`Attribute field attr_${key} not found`);
                                }
                            }
                        }
                    }
                }
            }
        }

        console.log('Form prefilled successfully');
        fetchGeneratedSearchTerm();
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
