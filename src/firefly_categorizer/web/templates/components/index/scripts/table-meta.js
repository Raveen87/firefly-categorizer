        function updateTableMeta(displayedCount) {
            const displayCount = typeof displayedCount === 'number' ? displayedCount : state.transactions.length;
            dom.tableSubtitle.textContent = `Showing ${displayCount} of ${state.totalTransactions} transactions.`;
            dom.metricTotal.textContent = state.totalTransactions.toLocaleString();
            dom.metricPage.textContent = `${state.currentPage} / ${state.totalPages}`;
        }
