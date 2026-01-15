        function runCategorization() {
            dom.loadingText.textContent = 'Categorizing...';
            dom.loadingState.classList.remove('hidden');

            const params = buildFilterParams();
            const eventSource = new EventSource(`/api/categorize-stream?${params.toString()}`);

            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
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

                    scheduleRender();
                }
            };

            eventSource.addEventListener('done', function() {
                eventSource.close();
                dom.loadingState.classList.add('hidden');
            });

            eventSource.onerror = function(event) {
                if (eventSource.readyState === EventSource.CLOSED) {
                    dom.loadingState.classList.add('hidden');
                } else {
                    console.error('EventSource failed:', event);
                    eventSource.close();
                    dom.loadingState.classList.add('hidden');
                }
            };
        }
