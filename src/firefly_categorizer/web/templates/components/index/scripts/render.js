        function renderTransactions() {
            dom.tbody.innerHTML = '';
            let displayedCount = 0;

            if (!state.transactions || state.transactions.length === 0) {
                dom.noData.textContent = 'No transactions found.';
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

            state.transactions.forEach(t => {
                const isCategorized = t.existing_category ? true : false;
                if (isCategorized && !showCategorized) {
                    return;
                }

                const row = document.createElement('tr');
                row.className = isCategorized ? 'table-row is-categorized' : 'table-row';

                let predictionName = 'Unknown';
                let confidence = '-';
                let predictedCat = null;

                if (t.prediction) {
                    predictionName = t.prediction.category.name;
                    predictedCat = t.prediction.category.name;
                    confidence = t.prediction.confidence.toFixed(2);
                }

                let optionsHtml = `<option value="" disabled ${!predictedCat ? 'selected' : ''}>Select Category</option>`;
                CATEGORIES.forEach(cat => {
                    const isSelected = (cat === predictedCat) ? 'selected' : '';
                    optionsHtml += `<option value="${cat}" ${isSelected}>${cat}</option>`;
                });

                const selectDisabled = isCategorized ? 'disabled' : '';
                const buttonDisabled = isCategorized ? 'disabled' : '';
                const buttonClass = isCategorized ? 'btn btn-disabled btn-xs' : 'btn btn-primary btn-xs';

                let categoryDisplay = '';
                if (isCategorized) {
                    const autoLabel = t.auto_approved ? '<span class="tag">Auto</span>' : '<span class="tag tag-muted">Existing</span>';
                    categoryDisplay = `<span class="font-semibold">${t.existing_category}</span> ${autoLabel}`;
                } else if (predictedCat) {
                    const sourceLabels = {
                        'memory_exact': 'M',
                        'memory_fuzzy': 'M~',
                        'tfidf': 'ML',
                        'llm': 'AI'
                    };
                    const sourceLabel = sourceLabels[t.prediction.source] || t.prediction.source;
                    categoryDisplay = `<span class="prediction">${predictionName}</span> <span class="tag tag-muted" title="${t.prediction.source}">${sourceLabel}</span>`;
                } else {
                    categoryDisplay = `<span class="text-muted">Unknown</span>`;
                }

                row.innerHTML = `
                    <td>${t.date_formatted}</td>
                    <td>${t.description}</td>
                    <td>${t.amount} ${t.currency}</td>
                    <td>${categoryDisplay}</td>
                    <td>${isCategorized ? '-' : confidence}</td>
                    <td class="flex items-center gap-2">
                        <select id="cat-${t.id}" class="select-input" ${selectDisabled}>
                            ${optionsHtml}
                        </select>
                        <button id="btn-${t.id}" onclick="saveTransaction('${t.id}', '${predictedCat || ''}')"
                            class="${buttonClass}" ${buttonDisabled}>Save</button>
                        <input type="hidden" id="raw-${t.id}" value='${t.raw_obj}'>
                    </td>
                `;
                dom.tbody.appendChild(row);
                displayedCount += 1;
            });

            updateTableMeta(displayedCount);
        }
