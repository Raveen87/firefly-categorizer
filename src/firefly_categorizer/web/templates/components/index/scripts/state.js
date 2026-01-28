let CATEGORIES = {{ categories | tojson }};
const state = {
    transactions: [],
    currentPage: 1,
    itemsPerPage: 50,
    totalPages: 1,
    totalTransactions: 0,
    renderScheduled: false,
    isCategorizing: false
};
const dom = {};
