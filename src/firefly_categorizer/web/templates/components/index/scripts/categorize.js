let categorizationSource = null;

function toggleControls(disable) {
    dom.startDate.disabled = disable;
    dom.endDate.disabled = disable;
    dom.scopeToggle.disabled = disable;
    dom.showCategorized.disabled = disable;
    dom.limitSelect.disabled = disable;
    dom.fetchBtn.disabled = disable;
    dom.paginationControls.forEach(el => {
        el.querySelectorAll('button').forEach(btn => btn.disabled = disable);
    });
}

function runCategorization() {
    // If already running, acting as Stop button
    if (categorizationSource) {
        categorizationSource.close();
        cleanupCategorization();
        return;
    }

    // Start state
    dom.categorizeBtn.textContent = 'Stop';
    dom.categorizeBtn.classList.remove('btn-secondary');
    dom.categorizeBtn.classList.add('btn-danger'); // Assuming btn-danger exists or will style it

    toggleControls(true);

    dom.loadingText.textContent = 'Categorizing...';
    dom.loadingState.classList.remove('hidden');

    const params = buildFilterParams();
    categorizationSource = new EventSource(`/api/categorize-stream?${params.toString()}`);

    categorizationSource.onmessage = function (event) {
        const data = JSON.parse(event.data);

        if (data.error) {
            console.error('Categorization error:', data.error);
            alert('Error during categorization: ' + data.error);
            // Use cleanup on error to reset UI
            if (categorizationSource) {
                categorizationSource.close();
                cleanupCategorization();
            }
            return;
        }

        const idx = state.transactions.findIndex(t => t.id === data.id);
        if (idx !== -1) {
            if (data.prediction) {
                state.transactions[idx].prediction = data.prediction;
            }
            if (data.existing_category) {
                state.transactions[idx].existing_category = data.existing_category;
            }
            if (data.auto_approved) {
                state.transactions[idx].auto_approved = data.auto_approved;
            }
            state.transactions[idx].processed = true;

            scheduleRender();
        }
    };

    categorizationSource.addEventListener('done', function () {
        if (categorizationSource) {
            categorizationSource.close();
            cleanupCategorization();
        }
    });

    categorizationSource.onerror = function (event) {
        if (categorizationSource && categorizationSource.readyState !== EventSource.CLOSED) {
            console.error('EventSource failed:', event);
        }
        if (categorizationSource) {
            categorizationSource.close();
            cleanupCategorization();
        }
    };
}

function cleanupCategorization() {
    categorizationSource = null;
    dom.loadingState.classList.add('hidden');

    // Reset button
    dom.categorizeBtn.textContent = 'Run categorization';
    dom.categorizeBtn.classList.remove('btn-danger');
    dom.categorizeBtn.classList.add('btn-secondary');

    // Unlock UI
    toggleControls(false);

    // Re-apply scope UI logic (e.g. disable date fields if "all" scope is selected)
    // This is important because toggleControls(false) enables everything blindly.
    if (typeof applyScopeUI === 'function') {
        applyScopeUI();
    }
}
