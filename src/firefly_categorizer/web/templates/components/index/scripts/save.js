        async function saveTransaction(transactionId, suggestedCategory) {
            const selectEl = document.getElementById(`cat-${transactionId}`);
            if (!selectEl) return;

            const categoryName = selectEl.value;
            const btn = document.getElementById(`btn-${transactionId}`);
            const transaction = state.transactions.find(t => t.id === transactionId);
            const existingTags = transaction && Array.isArray(transaction.existing_tags)
                ? transaction.existing_tags
                : [];

            if (!categoryName) {
                alert('Please select a category first.');
                return;
            }

            const spinnerHtml = `<div class="inline-spinner"></div>`;

            btn.disabled = true;
            selectEl.disabled = true;
            btn.innerHTML = spinnerHtml;
            btn.className = 'btn btn-ghost btn-xs';

            const rawInput = document.getElementById(`raw-${transactionId}`);
            const transactionObj = JSON.parse(rawInput.value);

            try {
                const response = await fetch('/learn', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        transaction: transactionObj,
                        category: { name: categoryName },
                        transaction_id: transactionId,
                        suggested_category: suggestedCategory || null,
                        existing_tags: existingTags
                    })
                });

                if (response.ok) {
                    const row = selectEl.closest('tr');
                    row.className = 'table-row is-categorized is-processed';

                    const dateCell = row.cells[0];
                    if (dateCell && !dateCell.querySelector('.processed-indicator')) {
                        const indicator = document.createElement('span');
                        indicator.className = 'processed-indicator tooltip';
                        indicator.setAttribute('data-tooltip', 'Already processed');
                        indicator.setAttribute('aria-label', 'Already processed');
                        indicator.setAttribute('role', 'img');
                        indicator.textContent = '✓';
                        dateCell.prepend(indicator);
                    }

                    const catCell = row.cells[3];
                    catCell.textContent = '';
                    const categorySpan = document.createElement('span');
                    categorySpan.className = 'font-semibold';
                    categorySpan.textContent = categoryName;
                    const savedSpan = document.createElement('span');
                    savedSpan.className = 'tag';
                    savedSpan.textContent = 'Saved';
                    catCell.append(categorySpan, document.createTextNode(' '), savedSpan);

                    const confCell = row.cells[4];
                    confCell.textContent = '-';

                    btn.remove();
                    selectEl.disabled = true;
                } else {
                    alert('Failed to update.');
                    btn.disabled = false;
                    selectEl.disabled = false;
                    btn.innerHTML = 'Save';
                    btn.className = 'btn btn-primary btn-xs';
                }
            } catch (error) {
                console.error('Error:', error);
                alert('An error occurred.');
                btn.disabled = false;
                selectEl.disabled = false;
                btn.innerHTML = 'Save';
                btn.className = 'btn btn-primary btn-xs';
            }
        }
