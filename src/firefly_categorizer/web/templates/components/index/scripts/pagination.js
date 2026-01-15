        function updatePagePicker() {
            const containers = document.querySelectorAll('.page-picker');
            const items = getPageItems(state.currentPage, state.totalPages);

            containers.forEach(container => {
                container.innerHTML = '';
                items.forEach(item => {
                    if (item === 'ellipsis') {
                        const ellipsis = document.createElement('span');
                        ellipsis.className = 'page-ellipsis';
                        ellipsis.textContent = '...';
                        container.appendChild(ellipsis);
                        return;
                    }

                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'page-number';
                    if (item === state.currentPage) {
                        button.classList.add('is-active');
                    }
                    button.textContent = String(item);
                    button.addEventListener('click', () => {
                        if (item === state.currentPage) {
                            return;
                        }
                        state.currentPage = item;
                        fetchTransactions();
                    });
                    container.appendChild(button);
                });
            });
        }

        function getPageItems(currentPage, totalPages) {
            if (totalPages <= 1) {
                return [1];
            }

            const windowSize = 2;
            const pages = new Set([1, totalPages]);
            for (let i = currentPage - windowSize; i <= currentPage + windowSize; i += 1) {
                if (i >= 1 && i <= totalPages) {
                    pages.add(i);
                }
            }

            const sorted = Array.from(pages).sort((a, b) => a - b);
            const items = [];

            sorted.forEach((page, index) => {
                if (index > 0) {
                    const prev = sorted[index - 1];
                    if (page > prev + 1) {
                        items.push('ellipsis');
                    }
                }
                items.push(page);
            });

            return items;
        }
