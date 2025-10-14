
// Check extension availabilty on load
document.addEventListener('DOMContentLoaded', function() {
    if (!isExtensionAvailable()) {
        console.warn("Chrome extension not detected. Scraping functionality will not work.");
        
        // Optionally disable the scrape button
        const scrapeBtn = document.getElementById('scrape-btn');
        if (scrapeBtn) {
            scrapeBtn.title = "Chrome extension required";
        }
    }
});

// Helper function to detect if running in extension context
function isExtensionAvailable() {
    return typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.sendMessage;
}

// Helper function to send messages to extension via bridge
function sendExtensionMessage(message) {
    return new Promise((resolve, reject) => {
        const requestId = Math.random().toString(36).substr(2, 9);
        
        // Listen for response
        const responseHandler = (event) => {
            if (event.data.type === 'EXTENSION_RESPONSE' && event.data.requestId === requestId) {
                window.removeEventListener('message', responseHandler);
                
                if (event.data.error) {
                    reject(new Error(event.data.error));
                } else {
                    resolve(event.data.response);
                }
            }
        };
        
        window.addEventListener('message', responseHandler);
        
        // Send message to bridge
        window.postMessage({
            type: 'EXTENSION_MESSAGE',
            requestId: requestId,
            message: message
        }, '*');
        
        // Timeout after 60 seconds
        setTimeout(() => {
            window.removeEventListener('message', responseHandler);
            reject(new Error('Extension communication timeout'));
        }, 60000);
    });
}
