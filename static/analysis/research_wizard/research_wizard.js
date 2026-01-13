(function () {
  window.wizardState = window.wizardState || {
    source: null,
    final: {
      offer: null,
      rrp: null
    },
    cex: {
      category: null,
      subcategory: null,
      model: null,
      attributes: {},
      prices: null,
      selectedOffer: null,
      suggestedRrpMethod: null,
      rrp: null,
    },
    ebay: {
      searchTerm: null,              // the text in the search box
      filters: {},                    // selectedFilters object (checkboxes + ranges)
      topFilters: {                   // top checkboxes like Sold, UK, Used
        sold: false,
        ukOnly: false,
        used: false
      },
      prices: null,                   // { min, avg, median, mode }
      selectedOffer: null,            // the value in offerInput
      suggestedPriceMethod: null,     // e.g., "median minus 1" logic
      rrp: null,                       // value in rrpInput
      margin: null,                     // value in marginInput
      listings: [],                    // raw results from renderResults
    }
  };


  const pageHistory = [];


  const openBtn = document.getElementById('researchWizard');
  const backdrop = document.getElementById('researchWizardModal');
  const modal = backdrop?.querySelector('.rw-modal');
  const closeBtn = modal.querySelector('.rw-close');

  if (!openBtn || !backdrop || !modal) return;

  function isWizardStateEmpty() {
    // Checks if both CEX and eBay have any useful data
    const cexData = wizardState.cex || {};
    const ebayData = wizardState.ebay || {};
    return !(
      (cexData.prices && cexData.selectedOffer) ||
      (ebayData.prices && ebayData.selectedOffer)
    );
  }

  function openWizard() {
    window.ResearchWizard.showOverview();
    backdrop.classList.remove('rw-hidden');
    requestAnimationFrame(() => {
      backdrop.classList.add('rw-visible');
      document.body.classList.add('rw-open');
    });
  }



  function closeWizard() {
    backdrop.classList.remove('rw-visible');
    document.body.classList.remove('rw-open');

    setTimeout(() => {
      backdrop.classList.add('rw-hidden');
    }, 250);
  }

  openBtn.addEventListener('click', openWizard);
  closeBtn?.addEventListener('click', closeWizard);

  /* Backdrop click */
  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) closeWizard();
  });

  /* ESC close */
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && backdrop.classList.contains('rw-visible')) {
      closeWizard();
    }
  });

  const pages = modal.querySelectorAll('.rw-page');

  // Track if we're in quick add mode
  let isQuickAddMode = false;

  function showPage(selector) {
    const current = modal.querySelector('.rw-page.rw-active');
    const newPage = modal.querySelector(selector);
    if (current && current !== newPage) pageHistory.push(current);

    pages.forEach(p => p.classList.remove('rw-active'));
    newPage?.classList.add('rw-active');

    // 🔁 Restore eBay state when entering eBay page
    if (selector === '.rw-page-ebay') {
      if (typeof window.restoreEbayWizardState === 'function') {
        window.restoreEbayWizardState();
      }
    }

    // Focus category when entering CeX page (from overview, not quick add)
    if (selector === '.rw-page-cex') {
      // Don't reset isQuickAddMode here - it's set before showPage is called
      // If it's true (from quick add), keep it; if false (from overview), keep it false
      updateCexButtonVisibility();
      
      // Restore category from wizard state if available
      if (typeof restoreCategoryFromWizardState === 'function') {
        restoreCategoryFromWizardState().then(categoryWasRestored => {
          // Only focus if not in quick add mode
          if (!isQuickAddMode) {
            requestAnimationFrame(() => {
              if (categoryWasRestored) {
                // Category was pre-selected, focus and open subcategory dropdown
                if (typeof subcategoryTomSelect !== 'undefined' && subcategoryTomSelect) {
                  // Wait for subcategories to be rendered and DOM to update
                  setTimeout(() => {
                    // Check if subcategories are available
                    const hasOptions = Object.keys(subcategoryTomSelect.options).length > 0;
                    if (hasOptions) {
                      subcategoryTomSelect.focus();
                      subcategoryTomSelect.open();
                    } else {
                      // Fallback to category if no subcategories yet
                      if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
                        categoryTomSelect.focus();
                      }
                    }
                  }, 300);
                }
              } else {
                // No category pre-selected, focus category dropdown
                if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
                  categoryTomSelect.focus();
                }
              }
            });
          }
        }).catch(() => {
          // If restoration fails, just focus category as fallback
          if (!isQuickAddMode) {
            requestAnimationFrame(() => {
              if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
                categoryTomSelect.focus();
              }
            });
          }
        });
      } else {
        // No restore function, just focus category
        if (!isQuickAddMode) {
          requestAnimationFrame(() => {
            if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
              categoryTomSelect.focus();
            }
          });
        }
      }
    }
  }

  function updateCexButtonVisibility() {
    const confirmBtn = document.getElementById('cexConfirmResearchButton');
    const quickAddBtn = document.getElementById('cexQuickAddButton');
    
    if (confirmBtn && quickAddBtn) {
      if (isQuickAddMode) {
        // Quick add mode: show Quick Add, hide Confirm
        confirmBtn.style.display = 'none';
        quickAddBtn.style.display = 'block';
      } else {
        // Deep research mode: show Confirm, hide Quick Add
        confirmBtn.style.display = 'block';
        quickAddBtn.style.display = 'none';
      }
    }
  }


  const optionButtons = modal.querySelectorAll('.rw-option');

  optionButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const source = btn.dataset.source;

      if (source === 'cex') {
        // Coming from overview, so not quick add mode
        isQuickAddMode = false;
        updateCexButtonVisibility();
        showPage('.rw-page-cex');
      } else if (source === 'ebay') {
        showPage('.rw-page-ebay');
      }
    });
  });

  /* Expose close */
  window.ResearchWizard = window.ResearchWizard || {};
  window.ResearchWizard.close = closeWizard;
  window.ResearchWizard.updateCexButtonVisibility = updateCexButtonVisibility;

  function resetWizardState() {
    // Clear the wizard state
    wizardState = {
      source: null,
      final: {
        offer: null,
        rrp: null
      },
      cex: {
        category: null,
        subcategory: null,
        model: null,
        attributes: {},
        prices: null,
        selectedOffer: null,
        suggestedRrpMethod: null,
        rrp: null,
      },
      ebay: {
        searchTerm: null,
        filters: {},
        topFilters: { sold: false, ukOnly: false, used: false },
        prices: null,
        selectedOffer: null,
        suggestedPriceMethod: null,
        rrp: null,
        margin: null,
        listings: [],
        category: null,
        uiState: { expandedSections: [], filterScroll: 0, resultsScroll: 0 }
      }
    };

    // Reset eBay UI if resetEbayAnalysis function exists
    if (typeof resetEbayAnalysis === 'function') {
      resetEbayAnalysis();
    }

    // Reset eBay search input
    const ebaySearchInput = document.getElementById('ebaySearchInput');
    if (ebaySearchInput) {
      ebaySearchInput.value = '';
    }

    // Reset CeX TomSelects if they exist globally
    if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
      categoryTomSelect.clear();
    }
    if (typeof subcategoryTomSelect !== 'undefined' && subcategoryTomSelect) {
      subcategoryTomSelect.clear();
    }
    if (typeof modelTomSelect !== 'undefined' && modelTomSelect) {
      modelTomSelect.clear();
    }

    // Reset CeX prices UI if function exists
    if (typeof resetCexPrices === 'function') {
      resetCexPrices();
    }

    // Re-render the overview with empty state
    renderOverview();
    
    // Update confirm button state (should be disabled after reset)
    updateConfirmButtonState();
  }

  function updateConfirmButtonState() {
    const confirmBtn = modal.querySelector('.rw-confirm');
    if (!confirmBtn) return;

    const { final } = wizardState;
    const hasOffer = final?.offer != null && final.offer > 0;
    const hasRrp = final?.rrp != null && final.rrp > 0;
    const isValid = hasOffer && hasRrp;

    confirmBtn.disabled = !isValid;
    if (isValid) {
      confirmBtn.classList.remove('disabled');
    } else {
      confirmBtn.classList.add('disabled');
    }
  }

  window.ResearchWizard.showOverview = () => {
    renderOverview();
    showPage('.rw-page-overview');

    // Add Restart button dynamically if it doesn't exist yet
    let overviewActions = modal.querySelector('.rw-page-overview .rw-actions');
    if (!overviewActions.querySelector('.rw-restart')) {
      const restartBtn = document.createElement('button');
      restartBtn.classList.add('rw-restart');
      restartBtn.textContent = 'Restart';
      restartBtn.addEventListener('click', () => {
        resetWizardState();
      });
      overviewActions.appendChild(restartBtn);
    }

    // Update confirm button state after rendering
    updateConfirmButtonState();
  };


  // NEW: show the source selection page
  window.ResearchWizard.showSourcePage = () => {
    showPage('.rw-page-source');
  };

  // Quick CeX entry: open wizard directly on the CeX page
  window.ResearchWizard.showCexQuickAdd = () => {
    // Set quick add mode
    isQuickAddMode = true;
    updateCexButtonVisibility();
    
    // Ensure backdrop is visible
    backdrop.classList.remove('rw-hidden');
    requestAnimationFrame(() => {
      backdrop.classList.add('rw-visible');
      document.body.classList.add('rw-open');
      showPage('.rw-page-cex');
      
      // Restore last selections and focus appropriately
      setTimeout(() => {
        if (typeof restoreLastQuickAddSelections === 'function') {
          restoreLastQuickAddSelections().then(restored => {
            if (restored) {
              // If restored, focus on model select
              setTimeout(() => {
                if (typeof modelTomSelect !== 'undefined' && modelTomSelect) {
                  modelTomSelect.focus();
                }
              }, 200);
            } else {
              // If not restored, focus on category
              if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
                categoryTomSelect.focus();
              }
            }
          });
        } else {
          // Fallback: just focus category
          if (typeof categoryTomSelect !== 'undefined' && categoryTomSelect) {
            categoryTomSelect.focus();
          }
        }
      }, 100);
    });
  };

 function renderOverview() {
  const container = document.getElementById('overviewContent');
  if (!container) return;

  const { cex, ebay, final } = wizardState;

  container.innerHTML = `
    <div class="overview-two-pane-layout">
      <div class="overview-cards-pane">
        <div class="overview-cards">
          ${renderEbayOverview(ebay)}
          ${renderCexOverview(cex)}
        </div>
      </div>

      <div class="overview-final-pane">
        <div class="overview-final">
          <h3>Final Pricing</h3>

          <div class="row">
            <label>Offer</label>
            <input
              type="number"
              step="0.01"
              id="finalOfferInput"
              placeholder="£"
              value="${final?.offer ?? ''}"
            />
          </div>

          <div class="row">
            <label>Suggested RRP</label>
            <input
              type="number"
              step="0.01"
              id="finalRrpInput"
              placeholder="£"
              value="${final?.rrp ?? ''}"
            />
          </div>
        </div>
      </div>
    </div>
  `;

  // navigation buttons
  container.querySelectorAll('.research-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (btn.dataset.source === 'cex') {
        // Coming from overview, so not quick add mode
        isQuickAddMode = false;
        updateCexButtonVisibility();
      }
      showPage(
        btn.dataset.source === 'ebay'
          ? '.rw-page-ebay'
          : '.rw-page-cex'
      );
    });
  });

  // wire inputs
  const offerInput = container.querySelector('#finalOfferInput');
  const rrpInput = container.querySelector('#finalRrpInput');

  offerInput?.addEventListener('input', () => {
    wizardState.final.offer = Number(offerInput.value) || null;
    console.log('Final offer updated:', wizardState.final.offer);
    updateConfirmButtonState();
  });

  rrpInput?.addEventListener('input', () => {
    wizardState.final.rrp = Number(rrpInput.value) || null;
    console.log('Final RRP updated:', wizardState.final.rrp);
    updateConfirmButtonState();
  });

  const ebaySearchInput = container.querySelector('.ebay-search-term');

  ebaySearchInput?.addEventListener('input', () => {
    wizardState.ebay.searchTerm = ebaySearchInput.value.trim();
  });

}

function renderEbayOverview(ebay) {
  const p = ebay.prices || {};

  return `
    <div class="market-card ebay">
      <div class="market-card-header">
        <h3>eBay</h3>
        <button class="research-btn" data-source="ebay">
          Research eBay
        </button>
      </div>

      <section>
        <h4>Search term</h4>
        <input
          type="text"
          class="ebay-search-term"
          placeholder="e.g. iPhone 13 Pro 128GB"
          value="${ebay.searchTerm ?? ''}"
        />
      </section>

      <section>
        <h4>Market stats</h4>
        <div class="row"><span>Avg</span><span>£${p.avg ? Number(p.avg).toFixed(2) : '-'}</span></div>
        <div class="row"><span>Median</span><span>£${p.median ? Number(p.median).toFixed(2) : '-'}</span></div>
        <div class="row"><span>Mode</span><span>£${p.mode ? Number(p.mode).toFixed(2) : '-'}</span></div>
      </section>

      <section>
        <h4>Suggested RRP</h4>
        <div class="big">
          £${ebay.rrp ? Number(ebay.rrp).toFixed(2) : '-'}
          ${ebay.suggestedPriceMethod ? `<small>${ebay.suggestedPriceMethod}</small>` : ''}
        </div>
      </section>

      <section>
        <h4>Selected offer</h4>
        <div class="big">
          £${ebay.selectedOffer ? Number(ebay.selectedOffer).toFixed(2) : '-'}
        </div>
      </section>
    </div>
  `;

  
}



function renderCexOverview(cex) {
  console.log(cex);
  return `
    <div class="market-card cex">
      <div class="market-card-header">
        <h3>CeX</h3>
        <button class="research-btn" data-source="cex">
          Research CeX
        </button>
      </div>

      ${cex.model?.name ? `
      <section>
        <h4>Model</h4>
        <div>${cex.model.name}</div>
      </section>
      ` : ''}

      <section>
        <h4>Sell price</h4>
        <div class="big">
          £${cex.prices?.cexSellingPrice ? Number(cex.prices.cexSellingPrice).toFixed(2) : '-'}
        </div>
      </section>

      <section>
        <h4>Suggested RRP</h4>
        <div class="big">
          £${cex.prices?.rrp ? Number(cex.prices.rrp).toFixed(2) : '-'}
          ${cex.suggestedRrpMethod ? `<small>${cex.suggestedRrpMethod}</small>` : ''}
        </div>
      </section>

      <section>
        <h4>Offers</h4>

        <div class="cex-offer-list">
          ${
            (cex.offers || []).map(offer => {
              const isActive =
                cex.selectedOffer &&
                offer.type === cex.selectedOffer.type;

              return `
                <div class="cex-offer-row
                            ${offer.risk}
                            ${isActive ? 'active' : ''}">
                  <span class="label">
                    ${offer.type.replace('_', ' ')}
                  </span>

                  <span class="price">
                    £${Number(offer.price).toFixed(2)}
                  </span>

                  <span class="margin">
                    ${offer.marginPct}%
                  </span>
                </div>
              `;
            }).join('') || '<div>—</div>'
          }
        </div>
      </section>
    </div>
  `;
}


  // Set up confirm button handler (button exists in template, not re-rendered)
  function setupConfirmButton() {
    const confirmBtn = modal.querySelector('.rw-confirm');
    if (!confirmBtn) return;

    // Remove any existing listeners by cloning the button
    const newConfirmBtn = confirmBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
    
    newConfirmBtn.addEventListener('click', () => {
      const { final, ebay, cex } = wizardState;

      // Require both final offer and final RRP
      if (!final?.offer || final.offer <= 0 || !final?.rrp || final.rrp <= 0) {
        alert('Please enter both Offer and Suggested RRP in the Final Pricing section.');
        return;
      }

      const itemName =
        cex.model?.name ||
        ebay.searchTerm ||
        '';

      const categoryName =
        cex.category?.name ||
        ebay.category?.name ||
        '';

      // Use only the final offer and final RRP from the inputs
      addSimpleItemToTable({
        category: categoryName,
        name: itemName,
        rrp: final.rrp,
        offer: final.offer
      });

      console.log('Confirmed research → added to table:', {
        category: categoryName,
        name: itemName,
        rrp: final.rrp,
        offer: final.offer
      });

      // Close the modal after adding the item
      closeWizard();
      
      // Reset wizard state for next time
      resetWizardState();
    });

    // Set initial disabled state
    updateConfirmButtonState();
  }

  // Set up the confirm button when modal is ready
  if (modal) {
    setupConfirmButton();
  }


})();
