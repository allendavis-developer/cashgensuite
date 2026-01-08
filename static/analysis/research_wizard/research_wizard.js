(function () {

  window.wizardState = window.wizardState || {
    source: null,
    cex: {
      category: null,
      subcategory: null,
      model: null,
      attributes: {},
      prices: null,
      selectedOffer: null,
      suggestedRrpMethod: null
    },
    ebay: {}
  };

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
    if (isWizardStateEmpty()) {
      showPage('.rw-page-source');
    } else {
      window.ResearchWizard.showOverview();
    }

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

  function showPage(selector) {
    pages.forEach(p => p.classList.remove('rw-active'));
    modal.querySelector(selector)?.classList.add('rw-active');
  }

  const optionButtons = modal.querySelectorAll('.rw-option');

  optionButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      const source = btn.dataset.source;

      if (source === 'cex') {
        showPage('.rw-page-cex');
      } else if (source === 'ebay') {
        showPage('.rw-page-ebay');
      }
    });
  });

  /* Expose close */
  window.ResearchWizard = window.ResearchWizard || {};
  window.ResearchWizard.close = closeWizard;

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
        wizardState = { source: null, cex: { category: null, subcategory: null, model: null, attributes: {}, prices: null, selectedOffer: null, suggestedRrpMethod: null }, ebay: {} };
        showPage('.rw-page-source');
      });
      overviewActions.appendChild(restartBtn);
    }
  };

  // NEW: show the source selection page
  window.ResearchWizard.showSourcePage = () => {
    showPage('.rw-page-source');
  };

  function renderOverview() {
    const container = document.getElementById('overviewContent');
    if (!container) return;

    const rows = [];

    // CeX row
    if (wizardState.cex?.prices && wizardState.cex?.selectedOffer) {
      const { prices, selectedOffer } = wizardState.cex;

      rows.push(`
        <tr class="overview-row cex">
          <td class="source">CeX</td>
          <td class="price">£${prices.cexSellingPrice}</td>
          <td class="rrp">
            ${wizardState.cex?.suggestedRrpMethod
              ? `<div class="rrp-percentage">${wizardState.cex.suggestedRrpMethod}</div>`
              : ''}
            <div>£${prices.rrp}</div>
          </td>
          <td class="offer ${selectedOffer.risk}">£${selectedOffer.price}
            <span class="offer-meta">${selectedOffer.type.replace('_', ' ')}</span>
          </td>
          <td class="status">
            <button class="row-btn complete">Complete</button>
          </td>
        </tr>
      `);
    } else {
      rows.push(`
        <tr class="overview-row cex">
          <td class="source">CeX</td>
          <td class="price">-</td>
          <td class="rrp">-</td>
          <td class="offer">-</td>
          <td class="status">
            <button class="row-btn compute-quick">Quick Compute</button>
            <button class="row-btn compute-research">Research</button>
          </td>
        </tr>
      `);
    }

    // eBay row
    const ebayData = wizardState.ebay || {};
    const ebayPrices = ebayData.prices || {};
    const selectedOffer = ebayData.selectedOffer || {};

    const hasEbayData = ebayPrices.marketPrice || ebayPrices.rrp || selectedOffer.price;

    rows.push(`
      <tr class="overview-row ebay">
        <td class="source">eBay</td>
        <td class="price">${ebayPrices.marketPrice ? `£${ebayPrices.marketPrice}` : '-'}</td>
        <td class="rrp">${ebayPrices.rrp ? `£${ebayPrices.rrp}` : '-'}</td>
        <td class="offer ${selectedOffer.risk || ''}">
          ${selectedOffer.price ? `£${selectedOffer.price}` : '-'}
          ${selectedOffer.type ? `<span class="offer-meta">${selectedOffer.type.replace('_', ' ')}</span>` : ''}
        </td>
        <td class="status">
          ${
            hasEbayData
              ? `<button class="row-btn complete">Complete</button>`
              : `<button class="row-btn compute-quick">Quick Compute</button>
                <button class="row-btn compute-research">Research</button>`
          }
        </td>
      </tr>
    `);

    container.innerHTML = `
      <div class="overview-table-wrapper">
        <table class="overview-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Market Price</th>
              <th>Suggested RRP</th>
              <th>Selected Offer</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${rows.join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  modal.querySelector('.rw-back')?.addEventListener('click', () => {
    showPage('.rw-page-cex');
  });

  modal.querySelector('.rw-confirm')?.addEventListener('click', () => {
    console.log('Confirmed research:', wizardState);
    closeWizard();
  });

})();
