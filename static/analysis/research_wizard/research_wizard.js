(function () {

  window.wizardState = window.wizardState || {
    source: null,
    cex: {
      category: null,
      subcategory: null,
      model: null,
      attributes: {},
      prices: null
    }
  };

  const openBtn = document.getElementById('researchWizard');
  const backdrop = document.getElementById('researchWizardModal');
  const modal = backdrop?.querySelector('.rw-modal');
  const closeBtn = modal.querySelector('.rw-close');

  if (!openBtn || !backdrop || !modal) return;
  
  function openWizard() {
    showPage('.rw-page-source');

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
        }
      });
    });

  /* Expose close */
  window.ResearchWizard = window.ResearchWizard || {};
  window.ResearchWizard.close = closeWizard;

  window.ResearchWizard.showOverview = () => {
    renderOverview();
    showPage('.rw-page-overview');
  };


  function renderOverview() {
    const container = document.getElementById('overviewContent');
    if (!container) return;

    const rows = [];

    if (wizardState.cex?.prices && wizardState.cex?.selectedOffer) {
      const { prices, selectedOffer } = wizardState.cex;

      rows.push(`
        <tr class="overview-row cex">
          <td class="source">CeX</td>
          <td class="price">£${prices.cexSellingPrice}</td>
          <td class="rrp">£${prices.rrp}</td>
          <td class="offer ${selectedOffer.risk}">
            £${selectedOffer.price}
            <span class="offer-meta">${selectedOffer.type.replace('_', ' ')}</span>
          </td>
        </tr>
      `);
    }

    if (!rows.length) {
      container.innerHTML = `<p class="overview-empty">No research completed yet.</p>`;
      return;
    }

    container.innerHTML = `
      <div class="overview-table-wrapper">
        <table class="overview-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Market Price</th>
              <th>Suggested RRP</th>
              <th>Selected Offer</th>
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
