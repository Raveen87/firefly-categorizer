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
                    row.className = 'table-row is-categorized';

                    const catCell = row.cells[3];
                    catCell.innerHTML = `<span class="font-semibold">${categoryName}</span> <span class="tag">Saved</span>`;

                    const confCell = row.cells[4];
                    confCell.innerHTML = '-';

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
