async function fetchTransactions(predict = false) {
    // Lock UI
    if (typeof toggleControls === 'function') toggleControls(true);
    if (dom.categorizeBtn) dom.categorizeBtn.disabled = true;

    dom.loadingText.textContent = predict ? 'Categorizing...' : 'Fetching...';
    dom.loadingState.classList.remove('hidden');

    if (!predict) {
        dom.tbody.innerHTML = '';
    }
    dom.noData.classList.add('hidden');
    if (dom.errorAlert) dom.errorAlert.classList.add('hidden');
    dom.paginationControls.forEach(el => el.classList.add('hidden'));

    const params = buildFilterParams({ includePredict: predict });
    syncUrl();

    try {
        const response = await fetch(`/api/transactions?${params.toString()}`);

        if (!response.ok) {
            let errorMessage = 'Error fetching transactions';
            try {
                const err = await response.json();
                errorMessage = err.detail || errorMessage;
            } catch (e) {
                errorMessage = `Error ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }

        const data = await response.json();

        if (data.transactions) {
            state.transactions = data.transactions;
            if (data.pagination) {
                state.totalPages = data.pagination.total_pages || 1;
                state.totalTransactions = data.pagination.total || 0;
            } else {
                state.totalPages = 1;
                state.totalTransactions = data.transactions.length;
            }
        } else {
            state.transactions = Array.isArray(data) ? data : [];
            state.totalPages = 1;
            state.totalTransactions = state.transactions.length;
        }

        renderTransactions();

    } catch (error) {
        console.error('Fetch error:', error);
        if (dom.errorAlert && dom.errorText) {
            dom.errorText.textContent = error.message || 'Error fetching data.';
            dom.errorAlert.classList.remove('hidden');
        } else {
            // Fallback if elements missing
            dom.noData.textContent = error.message || 'Error fetching data.';
            dom.noData.classList.add('text-danger');
            dom.noData.classList.remove('hidden');
        }
    } finally {
        dom.loadingState.classList.add('hidden');
        // Unlock UI
        if (typeof toggleControls === 'function') toggleControls(false);
        if (typeof applyScopeUI === 'function') applyScopeUI();
        if (dom.categorizeBtn) dom.categorizeBtn.disabled = false;
    }
}

async function fetchCategories() {
    if (dom.categoriesLoading) dom.categoriesLoading.classList.remove('hidden');
    if (dom.categoriesError) dom.categoriesError.classList.add('hidden');

    try {
        const response = await fetch('/api/categories');
        if (!response.ok) {
            throw new Error('Failed to fetch categories');
        }
        CATEGORIES = await response.json();

        // Re-render if we have transactions, to update dropdowns
        if (state.transactions && state.transactions.length > 0 && !state.isCategorizing) {
            renderTransactions();
        }

    } catch (error) {
        console.error('Error fetching categories:', error);
        if (dom.categoriesError) dom.categoriesError.classList.remove('hidden');
    } finally {
        if (dom.categoriesLoading) dom.categoriesLoading.classList.add('hidden');
    }
}
