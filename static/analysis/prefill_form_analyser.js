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
    
    console.log('Prefilling form with:', {categoryId, subcategoryId, modelId, attributesParam});
    
    try {
        // Parse attributes from URL-encoded JSON
        let attributes = [];
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
            categorySelect.value = categoryId;
            categorySelect.dispatchEvent(new Event('change'));
            
            // Wait for subcategorys to load
            await waitForElement('#subcategory option[value]:not([value=""])');
            
            // 2. Select subcategory
            const subcategorySelect = document.getElementById('subcategory');
            if (subcategorySelect) {
                subcategorySelect.value = subcategoryId;
                subcategorySelect.dispatchEvent(new Event('change'));
                
                // Wait for models to load
                await waitForElement('#model option[value]:not([value=""])');
                
                // 3. Select model
                const modelSelect = document.getElementById('model');
                if (modelSelect) {
                    modelSelect.value = modelId;
                    modelSelect.dispatchEvent(new Event('change'));
                    
                    // Wait for attributes to render
                    if (attributes.length > 0) {
                        await new Promise(resolve => setTimeout(resolve, 500));
                        
                        // 4. Fill in attributes
                        attributes.forEach(attr => {
                            const attrSelect = document.getElementById(`attr_${attr.id}`);
                            if (attrSelect) {
                                attrSelect.value = attr.value;
                                attrSelect.dispatchEvent(new Event('change'));
                                console.log(`Set attribute ${attr.id} to ${attr.value}`);
                            } else {
                                console.warn(`Attribute field attr_${attr.id} not found`);
                            }
                        });
                    }
                }
            }
        }
        
        console.log('Form prefilled successfully');
        
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
document.addEventListener('DOMContentLoaded', function() {
    const costInput = document.getElementById('cost-price');
    if (costInput && costInput.value) {
        setRRPAfterTable(costInput.value);
    }
    
    // Add prefill call here
    prefillFormFromURL();
});