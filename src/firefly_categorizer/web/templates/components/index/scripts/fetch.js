        async function fetchTransactions(predict = false) {
            dom.loadingText.textContent = predict ? 'Categorizing...' : 'Fetching...';
            dom.loadingState.classList.remove('hidden');

            if (!predict) {
                dom.tbody.innerHTML = '';
            }
            dom.noData.classList.add('hidden');
            dom.paginationControls.forEach(el => el.classList.add('hidden'));

            const params = buildFilterParams({ includePredict: predict });
            syncUrl();

            try {
                const response = await fetch(`/api/transactions?${params.toString()}`);
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

                dom.loadingState.classList.add('hidden');
                renderTransactions();

            } catch (error) {
                console.error('Fetch error:', error);
                dom.loadingState.classList.add('hidden');
                dom.noData.textContent = 'Error fetching data.';
                dom.noData.classList.remove('hidden');
            }
        }
