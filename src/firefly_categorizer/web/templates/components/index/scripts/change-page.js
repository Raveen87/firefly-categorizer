        function changePage(delta) {
            const newPage = state.currentPage + delta;
            if (newPage >= 1 && newPage <= state.totalPages) {
                state.currentPage = newPage;
                fetchTransactions();
            }
        }
