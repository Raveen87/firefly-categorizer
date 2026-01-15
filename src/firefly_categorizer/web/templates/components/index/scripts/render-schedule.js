        function scheduleRender() {
            if (state.renderScheduled) {
                return;
            }
            state.renderScheduled = true;
            requestAnimationFrame(() => {
                state.renderScheduled = false;
                renderTransactions();
            });
        }
