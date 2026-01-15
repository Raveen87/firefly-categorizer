        document.addEventListener('DOMContentLoaded', () => {
            dom.filterForm = document.getElementById('filter-form');
            dom.startDate = document.getElementById('start-date');
            dom.endDate = document.getElementById('end-date');
            dom.scopeToggle = document.getElementById('scope-all-toggle');
            dom.scopeStrip = document.getElementById('scope-strip');
            dom.scopeIndicator = document.getElementById('scope-indicator');
            dom.showCategorized = document.getElementById('show-categorized');
            dom.limitSelect = document.getElementById('limit-select');
            dom.fetchBtn = document.getElementById('fetch-btn');
            dom.categorizeBtn = document.getElementById('categorize-btn');
            dom.tableSubtitle = document.getElementById('table-subtitle');
            dom.metricTotal = document.getElementById('metric-total');
            dom.metricPage = document.getElementById('metric-page');
            dom.loadingState = document.getElementById('loading-state');
            dom.loadingText = document.getElementById('loading-text');
            dom.noData = document.getElementById('no-data-message');
            dom.tbody = document.getElementById('transactions-body');
            dom.paginationControls = document.querySelectorAll('.pagination-controls');

            state.itemsPerPage = parseInt(dom.limitSelect.value, 10) || 50;

            initFromQuery();
            applyScopeUI();

            dom.filterForm.addEventListener('submit', handleFilterSubmit);
            dom.scopeToggle.addEventListener('change', handleScopeChange);
            dom.limitSelect.addEventListener('change', handleLimitChange);
            dom.showCategorized.addEventListener('change', () => renderTransactions());
            dom.categorizeBtn.addEventListener('click', runCategorization);
            dom.startDate.addEventListener('change', updateScopeMeta);
            dom.endDate.addEventListener('change', updateScopeMeta);

            fetchTransactions();
        });
