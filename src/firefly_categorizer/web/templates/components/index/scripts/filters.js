        function initFromQuery() {
            const params = new URLSearchParams(window.location.search);
            const page = parseInt(params.get('page') || '1', 10);
            const limit = parseInt(params.get('limit') || '', 10);
            const scope = params.get('scope');

            if (!Number.isNaN(page) && page > 0) {
                state.currentPage = page;
            }

            if (!Number.isNaN(limit) && limit > 0) {
                state.itemsPerPage = limit;
                dom.limitSelect.value = String(limit);
            }

            dom.scopeToggle.checked = scope === 'all';
        }

        function isAllScope() {
            return dom.scopeToggle.checked;
        }

        function applyScopeUI() {
            const allScope = isAllScope();
            const dateFields = document.querySelectorAll('[data-filter="date"]');
            dateFields.forEach((field) => {
                field.classList.toggle('is-disabled', allScope);
                field.classList.toggle('is-hidden', allScope);
            });
            dom.startDate.disabled = allScope;
            dom.endDate.disabled = allScope;
            dom.showCategorized.disabled = false;

            updateScopeMeta();
        }

        function updateScopeMeta() {
            const allScope = isAllScope();
            dom.scopeIndicator.textContent = allScope ? 'All history' : 'Date range';
            dom.scopeStrip.textContent = allScope
                ? 'Filters off - displaying all transactions'
                : 'Filters on - using date range';
            dom.scopeStrip.classList.toggle('is-all', allScope);
            if (dom.fetchBtn) {
                dom.fetchBtn.textContent = allScope ? 'Fetch all' : 'Fetch range';
            }
        }

        function handleFilterSubmit(event) {
            event.preventDefault();
            state.currentPage = 1;
            updateScopeMeta();
            fetchTransactions();
        }

        function handleScopeChange() {
            state.currentPage = 1;
            applyScopeUI();
            fetchTransactions();
        }

        function handleLimitChange() {
            state.itemsPerPage = parseInt(dom.limitSelect.value, 10) || state.itemsPerPage;
            state.currentPage = 1;
            fetchTransactions();
        }

        function buildFilterParams(options = {}) {
            const params = new URLSearchParams();
            const { includePredict = false } = options;

            if (isAllScope()) {
                params.set('scope', 'all');
            } else {
                if (dom.startDate.value) {
                    params.set('start_date', dom.startDate.value);
                }
                if (dom.endDate.value) {
                    params.set('end_date', dom.endDate.value);
                }
            }

            if (includePredict) {
                params.set('predict', 'true');
            }

            params.set('page', state.currentPage);
            params.set('limit', state.itemsPerPage);

            return params;
        }

        function syncUrl() {
            const params = buildFilterParams();
            const query = params.toString();
            const url = query ? `${window.location.pathname}?${query}` : window.location.pathname;
            window.history.replaceState({}, '', url);
        }
