function shouldDisplayTransaction(transaction, showCategorized) {
    return showCategorized || !transaction.existing_category;
}

function buildTransactionRow(transaction) {
    const isCategorized = transaction.existing_category ? true : false;
    const isProcessed = transaction.processed ? true : isCategorized;
    const transactionId = String(transaction.id);
    const rowActionsDisabled = isCategorized
        || state.isCategorizing
        || state.pendingSaves.has(transactionId);
    const row = document.createElement('tr');
    row.dataset.transactionId = transactionId;
    row.className = `table-row${isCategorized ? ' is-categorized' : ''}${isProcessed ? ' is-processed' : ''}`;

    let predictionName = 'Unknown';
    let confidence = '-';
    let predictedCat = null;

    if (transaction.prediction) {
        predictionName = transaction.prediction.category.name;
        predictedCat = transaction.prediction.category.name;
        confidence = transaction.prediction.confidence.toFixed(2);
    }

    const buttonClass = rowActionsDisabled ? 'btn btn-disabled btn-xs' : 'btn btn-primary btn-xs';
    const dateCell = document.createElement('td');
    if (isProcessed) {
        const indicator = document.createElement('span');
        indicator.className = 'processed-indicator tooltip';
        indicator.setAttribute('data-tooltip', 'Already processed');
        indicator.setAttribute('aria-label', 'Already processed');
        indicator.setAttribute('role', 'img');
        indicator.textContent = '✓';
        dateCell.appendChild(indicator);
    }
    const dateSpan = document.createElement('span');
    dateSpan.textContent = transaction.date_formatted ?? '';
    dateCell.appendChild(dateSpan);

    const descriptionCell = document.createElement('td');
    descriptionCell.textContent = transaction.description ?? '';

    const amountCell = document.createElement('td');
    amountCell.textContent = `${transaction.amount ?? ''} ${transaction.currency ?? ''}`.trim();

    const categoryCell = document.createElement('td');
    if (isCategorized) {
        const categorySpan = document.createElement('span');
        categorySpan.className = 'font-semibold';
        categorySpan.textContent = transaction.existing_category ?? '';
        const statusTag = document.createElement('span');
        statusTag.className = transaction.auto_approved ? 'tag' : 'tag tag-muted';
        statusTag.textContent = transaction.auto_approved ? 'Auto' : 'Existing';
        categoryCell.append(categorySpan, document.createTextNode(' '), statusTag);
    } else if (predictedCat) {
        const sourceLabels = {
            'memory_exact': 'M',
            'memory_fuzzy': 'M~',
            'tfidf': 'ML',
            'llm': 'AI'
        };
        const predictionSpan = document.createElement('span');
        predictionSpan.className = 'prediction';
        predictionSpan.textContent = predictionName;
        const sourceTag = document.createElement('span');
        sourceTag.className = 'tag tag-muted';
        sourceTag.title = transaction.prediction.source;
        sourceTag.textContent = sourceLabels[transaction.prediction.source] || transaction.prediction.source;
        categoryCell.append(predictionSpan, document.createTextNode(' '), sourceTag);
    } else {
        const unknownSpan = document.createElement('span');
        unknownSpan.className = 'text-muted';
        unknownSpan.textContent = 'Unknown';
        categoryCell.appendChild(unknownSpan);
    }

    const confidenceCell = document.createElement('td');
    confidenceCell.textContent = isCategorized ? '-' : confidence;

    const actionsCell = document.createElement('td');
    actionsCell.className = 'flex items-center gap-2';

    const select = document.createElement('select');
    select.id = `cat-${transactionId}`;
    select.className = 'select-input';
    select.disabled = rowActionsDisabled;

    const placeholderOption = document.createElement('option');
    placeholderOption.value = '';
    placeholderOption.disabled = true;
    placeholderOption.selected = !predictedCat;
    placeholderOption.textContent = 'Select Category';
    select.appendChild(placeholderOption);

    CATEGORIES.forEach(cat => {
        const option = document.createElement('option');
        option.value = cat;
        option.selected = cat === predictedCat;
        option.textContent = cat;
        select.appendChild(option);
    });

    const saveButton = document.createElement('button');
    saveButton.id = `btn-${transactionId}`;
    saveButton.className = buttonClass;
    saveButton.disabled = rowActionsDisabled;
    saveButton.textContent = 'Save';
    saveButton.addEventListener('click', () => saveTransaction(transactionId, predictedCat || ''));

    const rawInput = document.createElement('input');
    rawInput.type = 'hidden';
    rawInput.id = `raw-${transactionId}`;
    rawInput.value = transaction.raw_obj ?? '';

    actionsCell.append(select, saveButton, rawInput);
    row.append(dateCell, descriptionCell, amountCell, categoryCell, confidenceCell, actionsCell);
    return row;
}

function setTransactionRowActionsDisabled(disable) {
    dom.tbody.querySelectorAll('tr[data-transaction-id]').forEach(row => {
        const transactionId = row.dataset.transactionId;
        const transaction = state.transactions.find(t => String(t.id) === String(transactionId));
        const shouldDisable = disable
            || state.pendingSaves.has(String(transactionId))
            || (transaction && transaction.existing_category ? true : false);
        row.querySelectorAll('select[id^="cat-"], button[id^="btn-"]').forEach(control => {
            control.disabled = shouldDisable;
            if (control.tagName === 'BUTTON') {
                control.className = shouldDisable ? 'btn btn-disabled btn-xs' : 'btn btn-primary btn-xs';
            }
        });
    });
}

function updateDisplayedCountMeta() {
    updateTableMeta(dom.tbody.children.length);
}

function escapeCssAttributeValue(value) {
    if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') {
        return CSS.escape(value);
    }
    return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\]/g, '\\]');
}

function updateTransactionRow(transactionId) {
    const normalizedTransactionId = String(transactionId);
    const transaction = state.transactions.find(t => String(t.id) === normalizedTransactionId);
    if (!transaction) {
        return;
    }

    const escapedTransactionId = escapeCssAttributeValue(normalizedTransactionId);
    const existingRow = dom.tbody.querySelector(`tr[data-transaction-id="${escapedTransactionId}"]`);
    const showCategorized = dom.showCategorized.checked;

    if (state.pendingSaves.has(normalizedTransactionId)) {
        return;
    }

    if (!shouldDisplayTransaction(transaction, showCategorized)) {
        if (existingRow) {
            existingRow.remove();
            updateDisplayedCountMeta();
        }
        return;
    }

    const newRow = buildTransactionRow(transaction);
    if (existingRow) {
        existingRow.replaceWith(newRow);
        return;
    }

    // Fallback for out-of-sync DOM state: perform a full render to restore row order.
    scheduleRender();
}

function renderTransactions() {
    dom.tbody.innerHTML = '';

    if (!state.transactions || state.transactions.length === 0) {
        dom.noData.textContent = 'No transactions found.';
        dom.noData.classList.remove('text-danger');
        dom.noData.classList.remove('hidden');
        dom.paginationControls.forEach(el => el.classList.add('hidden'));
        updateTableMeta(0);
        return;
    }
    dom.noData.classList.add('hidden');
    dom.paginationControls.forEach(el => el.classList.remove('hidden'));

    document.querySelectorAll('.current-page-display').forEach(el => el.textContent = state.currentPage);
    document.querySelectorAll('.total-pages-display').forEach(el => el.textContent = state.totalPages);
    document.querySelectorAll('.total-items-display').forEach(el => el.textContent = state.totalTransactions);
    document.querySelectorAll('.prev-page-btn').forEach(btn => btn.disabled = state.currentPage <= 1);
    document.querySelectorAll('.next-page-btn').forEach(btn => btn.disabled = state.currentPage >= state.totalPages);
    updatePagePicker();

    const showCategorized = dom.showCategorized.checked;
    const fragment = document.createDocumentFragment();

    state.transactions.forEach(transaction => {
        if (!shouldDisplayTransaction(transaction, showCategorized)) {
            return;
        }
        fragment.appendChild(buildTransactionRow(transaction));
    });

    dom.tbody.appendChild(fragment);
    updateDisplayedCountMeta();
}
